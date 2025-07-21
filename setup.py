from setuptools import setup, find_packages

setup(
    name='media_server',
    version='0.1.0',
    author='AI Agent',
    description='A simple HTTP server to list media files in a directory.',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    packages=find_packages(exclude=['tests*']),
    install_requires=[
        'absl-py',
        'keras',
        'torch',
        # Add other dependencies here as they are identified
    ],
    entry_points={
        'console_scripts': [
            'media-server=media_server.server:main',
        ],
    },
    python_requires='>=3.6',
)
