"""One weekly report format for HTTP uploads, direct files and Agent inputs."""
from .core import FIELDS, report_markdown, validate_week

PLACEHOLDER = '【请填写；如不适用请写“未说明”】'


def validate_fields(fields):
    if not isinstance(fields, dict) or set(fields) != set(FIELDS):
        raise ValueError('报告必须包含本周完成、结果与证据、问题与阻塞、下周计划四个栏目')
    for value in fields.values():
        if not isinstance(value, str) or not value.strip() or len(value) > 12000:
            raise ValueError('四个栏目均须填写，每项不超过 12000 字；未知内容请写“未说明”')
        if PLACEHOLDER in value:
            raise ValueError('请替换模板中的填写提示后再上传')
        if any(line.startswith('# ') or line.startswith('## ') for line in value.splitlines()):
            raise ValueError('栏目内容不能包含一级或二级标题；小标题可使用 ###')
    return {k: fields[k].strip() for k in FIELDS}


def template(name, week):
    validate_week(week)
    return report_markdown(name, week, dict.fromkeys(FIELDS, PLACEHOLDER))


def parse_report(text, name, week):
    validate_week(week)
    if not isinstance(text, str):
        raise ValueError('周报应为 UTF-8 Markdown 文本')
    text = text.lstrip('\ufeff').replace('\r\n', '\n').strip()
    lines = text.splitlines()
    if not lines or lines[0] != f'# {name} · {week} 科研周报':
        raise ValueError('周报标题与所选成员或周次不一致，请下载对应模板')
    headings = [line[3:] for line in lines[1:] if line.startswith('## ')]
    if headings != list(FIELDS.values()):
        raise ValueError('四个二级标题必须完整、唯一并按模板顺序排列')
    out, current = {}, None
    by_title = {v: k for k, v in FIELDS.items()}
    for line in lines[1:]:
        if line.startswith('## '):
            current = by_title[line[3:]]
            out[current] = ''
        elif current is not None:
            out[current] += line + '\n'
        elif line.strip():
            raise ValueError('标题与第一个栏目之间不能添加额外内容')
    return validate_fields(out)
