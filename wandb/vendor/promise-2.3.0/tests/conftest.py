from sys import version_info

collect_ignore = []
if version_info[:2] < (3, 4):
    collect_ignore.append("test_awaitable.py")
if version_info[:2] < (3, 5):
    collect_ignore.append("test_awaitable_35.py")
    collect_ignore.append("test_dataloader_awaitable_35.py")
