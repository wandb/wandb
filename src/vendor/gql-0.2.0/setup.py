from setuptools import setup, find_packages

setup(
    name='gql',
    version='0.2.0',
    description='GraphQL client for Python',
    long_description=open('README.md').read(),
    long_description_content_type="text/markdown",
    url='https://github.com/graphql-python/gql',
    author='Syrus Akbary',
    author_email='me@syrusakbary.com',
    license='MIT',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Libraries',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: Implementation :: PyPy',
    ],
    keywords='api graphql protocol rest relay gql client',
    packages=find_packages(include=["gql*"]),
    install_requires=[
        'six>=1.10.0',
        'graphql-core>=0.5.0,<2',
        'promise>=2.0,<3',
        'requests>=2.12,<3'
    ],
    tests_require=[
        'pytest>=3,<4',
        'pytest-cov>=2.8,<3',
        'mock>=3,<4',
        'vcrpy>=2.1,<3'
    ],
)
