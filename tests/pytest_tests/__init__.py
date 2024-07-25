from hypothesis import settings

settings.register_profile("ci", max_examples=10)
settings.load_profile("ci")
