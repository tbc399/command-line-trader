from setuptools import setup, find_packages


setup(
    name='main',
    version='0.1',
    packages=find_packages(),
    install_requires=[
        'Click',
        'httpx==0.16.1',
        'mplfinance==0.12.7a0',
        'pydantic==1.7.2',
        'tabulate==0.8.7'
    ],
    entry_points='''
        [console_scripts]
        brkr=clb.main:cli
    ''',
)
