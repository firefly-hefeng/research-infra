"""Minimal real file locking for the local Windows runner, never production imports."""
import errno
import msvcrt
import os
import time

LOCK_EX, LOCK_NB, LOCK_UN = 2, 4, 8


def flock(file, operation):
    fd = file if isinstance(file, int) else file.fileno()
    position = os.lseek(fd, 0, os.SEEK_CUR)
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        if operation == LOCK_UN:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return
        if operation not in (LOCK_EX, LOCK_EX | LOCK_NB):
            raise ValueError('Only exclusive local development locks are supported')
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if operation & LOCK_NB:
                    raise BlockingIOError(errno.EAGAIN, 'File is locked') from error
                time.sleep(0.05)
    finally:
        os.lseek(fd, position, os.SEEK_SET)
