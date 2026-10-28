"""Strict daily reports, stored separately from weekly summary inputs."""
import datetime as dt
import re
from .reports import PLACEHOLDER, validate_fields

FIELDS = {'done': '今日完成', 'results': '结果与证据', 'blockers': '问题与阻塞', 'next': '明日计划'}


def validate_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        raise ValueError('日报日期应为 YYYY-MM-DD')
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError('日报日期不是有效的日历日期') from None
    return value


def fields_for_daily(fields):
    if not isinstance(fields, dict) or set(fields) != set(FIELDS):
        raise ValueError('日报必须包含今日完成、结果与证据、问题与阻塞、明日计划四个栏目')
    return {key: value.replace('\r\n', '\n') for key, value in validate_fields(fields).items()}


def markdown(name, day, fields):
    return f'# {name} · {day} 科研日报\n\n' + '\n\n'.join(
        f'## {title}\n\n{fields[key].strip()}' for key, title in FIELDS.items()) + '\n'


def template(name, day):
    validate_date(day)
    return markdown(name, day, dict.fromkeys(FIELDS, PLACEHOLDER))


def parse_report(text, name, day):
    validate_date(day)
    if not isinstance(text, str):
        raise ValueError('日报应为 UTF-8 Markdown 文本')
    lines = text.lstrip('\ufeff').replace('\r\n', '\n').strip().splitlines()
    if not lines or lines[0] != f'# {name} · {day} 科研日报':
        raise ValueError('日报标题与所选成员或日期不一致，请下载对应模板')
    if [line[3:] for line in lines[1:] if line.startswith('## ')] != list(FIELDS.values()):
        raise ValueError('四个二级标题必须完整、唯一并按日报模板顺序排列')
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
    return fields_for_daily(out)
