try:
    from itertools import imap
    normal_map = map
except:
    def normal_map(func, iter):
        return list(map(func, iter))
    imap = map
