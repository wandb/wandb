def process(p, f, args, kwargs):
    try:
        val = f(*args, **kwargs)
        p.do_resolve(val)
    except Exception as e:
        p.do_reject(e)
