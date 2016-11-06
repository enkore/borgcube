import re
from glob import glob
from os.path import basename
from os.path import splitext
from pathlib import Path

from setuptools import find_packages
from setuptools import setup


def read(file):
    with (Path(__file__).parent / file).open() as fd:
        return fd.read()


setup(
    name='borgcube',
    description='A backup system built on Borg.',
    license='GPLv2',
    long_description='%s\n%s' % (
        re.compile('^.. start-badges.*^.. end-badges', re.M | re.S).sub('', read('README.rst')),
        re.sub(':[a-z]+:`~?(.*?)`', r'``\1``', read('CHANGELOG.rst'))
    ),
    author='Marian Beermann',
    author_email='public+borgcube@enkore.de',
    url='https://github.com/enkore/borgcube',
    packages=find_packages('src'),
    package_dir={'': 'src'},
    py_modules=[splitext(basename(path))[0] for path in glob('src/*.py')],
    include_package_data=True,
    zip_safe=False,
    classifiers=[
        # complete classifier list: http://pypi.python.org/pypi?%3Aaction=list_classifiers
        'Development Status :: 2 - Pre-Alpha',
        'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
        'Programming Language :: Python :: 3',
        'Topic :: System :: Archiving :: Backup',
        'Environment :: Web Environment',
    ],
    keywords=[
    ],
    install_requires=[
        'borgbackup',
        'django>=1.10,<1.11',
        'django-jsonfield',
        'pyzmq',
    ],
    extras_require={
    },
    entry_points={
        'console_scripts': [
            'borgcubed = borgcube.entrypoints:daemon',
            'borgcube-proxy = borgcube.entrypoints:proxy',
        ]
    }
#    entry_points={
#        'console_scripts': [
#            'nameless = nameless.cli:main',
#        ]
#    },
)
