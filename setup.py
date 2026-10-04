#!/usr/bin/env python3
"""
Setup script for Morning Quiz Bot
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README if it exists
this_directory = Path(__file__).parent
readme_path = this_directory / "README.md"
long_description = ""
if readme_path.exists():
    long_description = readme_path.read_text(encoding='utf-8')

setup(
    name="morning-quiz-bot",
    version="1.0.0",
    author="Morning Quiz Bot Team",
    author_email="",
    description="Telegram bot for conducting quizzes with rating system",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/your-repo/morning-quiz-bot",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    ],
    python_requires=">=3.10",
    install_requires=[
        "python-telegram-bot[job-queue,socks]==22.8",
        "python-dotenv>=0.19.0",
        "APScheduler>=3.9.0",
        "pytz>=2022.1",
        "aiofiles>=0.23.0",
        "openai>=1.0.0",  # Для работы с OpenRouter API (qwen/qwen3-max)
        "sqlalchemy[asyncio]>=2.0.43,<2.1",
        "asyncpg>=0.30.0,<1",
        "alembic>=1.15.2,<2",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "black>=22.0.0",
            "flake8>=4.0.0",
            "mypy>=0.950",
        ],
        "database": [
            "sqlalchemy[asyncio]>=2.0.43,<2.1",
            "asyncpg>=0.30.0,<1",
            "alembic>=1.15.2,<2",
        ],
        "monitoring": [
            "prometheus-client>=0.14.0",
        ],
        "images": [
            "Pillow>=9.0.0",
            "requests>=2.28.0",
            "aiohttp>=3.8.0",
        ],
        "ai": [
            "openai>=1.0.0",
            "anthropic>=0.3.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "morning-quiz-bot=bot:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
