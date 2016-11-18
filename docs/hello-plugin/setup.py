from setuptools import setup

setup(
    name='borgcube-hello-plugin',
    description='A plugin that says Hello World',
    py_modules=['hello_plugin'],
    install_requires=[
        'borgcube',
    ],
    entry_points={
        'borgcube0': [
            'hello_plugin = hello_plugin',
        ]
    }
)
