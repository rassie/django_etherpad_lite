from setuptools import setup, find_packages

setup(
    name='etherpadlite',
    version='0.1',
    author='Sofian Benaissa',
    author_email='me@sfyn.net',
    url='https://github.com/sfyn/django-etherpad-lite',
    description='Etherpad-lite integration for Django',
    packages=find_packages(),
    zip_safe=False,
    install_requires=[
        'Django',
        'PyEtherpadLite',
    ],
    dependency_links=[
        # No release on PyPI for now
        'https://github.com/devjones/PyEtherpadLite/zipball/master#egg' +
        '=PyEtherpadLite',
    ],
    license='GPL3',
    include_package_data=True,
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Framework :: Django',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Operating System :: OS Independent',
    ],
)
