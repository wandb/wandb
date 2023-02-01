import sys
from setuptools import setup, find_packages

if sys.version_info[0] < 3:
    import __builtin__ as builtins
else:
    import builtins

builtins.__SETUP__ = True

version = __import__("promise").get_version()


IS_PY3 = sys.hexversion >= 0x03000000

tests_require = [
    "pytest>=2.7.3",
    "pytest-cov",
    "coveralls",
    "futures",
    "pytest-benchmark",
    "mock",
]
if IS_PY3:
    tests_require += ["pytest-asyncio"]


setup(
    name="promise",
    version=version,
    description="Promises/A+ implementation for Python",
    long_description=open("README.rst").read(),
    url="https://github.com/syrusakbary/promise",
    download_url="https://github.com/syrusakbary/promise/releases",
    author="Syrus Akbary",
    author_email="me@syrusakbary.com",
    license="MIT",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.3",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: Implementation :: PyPy",
        "License :: OSI Approved :: MIT License",
    ],
    keywords="concurrent future deferred promise",
    packages=find_packages(exclude=["tests"]),
    # PEP-561: https://www.python.org/dev/peps/pep-0561/
    package_data={"promise": ["py.typed"]},
    extras_require={"test": tests_require},
    install_requires=[
        "typing>=3.6.4; python_version < '3.5'",
        "six"
    ],
    tests_require=tests_require,
)
