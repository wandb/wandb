from setuptools import setup, find_packages
from setuptools.command.test import test as TestCommand
import sys

if sys.version_info[0] < 3:
    import __builtin__ as builtins
else:
    import builtins

# This is a bit (!) hackish: we are setting a global variable so that the main
# graphql __init__ can detect if it is being loaded by the setup routine, to
# avoid attempting to load components that aren't built yet:
# the numpy distutils extensions that are used by scikit-learn to recursively
# build the compiled extensions in sub-packages is based on the Python import
# machinery.
if 'test' not in sys.argv:
    builtins.__GRAPHQL_SETUP__ = True

version = __import__('graphql').get_version()

install_requires = [
    'six>=1.10.0',
    'promise>=2.0'
]

tests_requires = [
    'pytest==3.0.2',
    'pytest-django==2.9.1',
    'pytest-cov==2.3.1',
    'coveralls',
    'gevent==1.1rc1',
    'six>=1.10.0',
    'pytest-benchmark==3.0.0',
    'pytest-mock==1.2',
]

class PyTest(TestCommand):
    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = ['graphql', '-vrsx']
        self.test_suite = True

    def run_tests(self):
        #import here, cause outside the eggs aren't loaded
        import pytest
        errno = pytest.main(self.test_args)
        sys.exit(errno)


setup(
    name='graphql-core',
    version=version,
    description='GraphQL implementation for Python',
    url='https://github.com/graphql-python/graphql-core',
    download_url='https://github.com/graphql-python/graphql-core/releases',
    author='Syrus Akbary, Jake Heinz, Taeho Kim',
    author_email='Syrus Akbary <me@syrusakbary.com>, Jake Heinz <me@jh.gg>, Taeho Kim <dittos@gmail.com>',
    license='MIT',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Libraries',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: Implementation :: PyPy',
        'License :: OSI Approved :: MIT License',
        'Topic :: Database :: Front-Ends',
        'Topic :: Internet :: WWW/HTTP',
    ],

    keywords='api graphql protocol rest',
    packages=find_packages(exclude=['tests', 'tests_py35']),
    install_requires=install_requires,
    tests_require=tests_requires,
    cmdclass = {'test': PyTest},
    extras_require={
        'gevent': [
            'gevent==1.1rc1'
        ],
        'test': tests_requires
    }
)
