import datetime

# Only retry requests for 20 seconds in the public api
RETRY_TIMEDELTA = datetime.timedelta(seconds=20)
