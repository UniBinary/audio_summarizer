from pathlib import Path
from setuptools import setup, find_packages

here = Path(__file__).parent
long_description = ""
readme = here / "README.md"
if readme.exists():
    long_description = readme.read_text(encoding="utf-8")

setup(
    name="audio_summarizer",                 # 包名，发布到 PyPI 时使用
    version="1.0a1",                         # 初始版本号，发布前更新
    description="一个用于总结音频文件和视频音轨的内容的工具。",  # 简短描述
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="UniBinary",
    author_email="tp114514251@outlook.com",
    url="https://github.com/UniBinary/audio_summarizer",     # 仓库地址或项目主页

    packages=find_packages(),
    package_data={
        "audiosummarizer": ["assets/*",]
    },

    python_requires=">=3.8",
    install_requires=[
        "oss2>=2.19.1",  # 阿里云OSS SDK
        "dashscope>=1.25.12",  # 阿里云DashScope SDK
        "openai>=1.0.0",  # DeepSeek API客户端
        # 在此添加运行时依赖，例如 "ffmpeg-python>=0.2.0"
    ],

    entry_points={
        "console_scripts": [
            # 将脚本暴露为命令行工具，修改为你项目的入口函数
            "audiosummarizer=audiosummarizer.main:summarize",
            "sumaudio=audiosummarizer.main:summarize"
        ]
    },

    license="MIT",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "Natural Language :: Chinese (Simplified)",
        "Topic :: Multimedia :: Video",
        "Topic :: Multimedia :: Sound/Audio",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Operating System :: Microsoft :: Windows"
    ],

    # metadata for upload
    project_urls={
        "Source": "https://github.com/UniBinary/audio_summarizer",
        "Tracker": "https://github.com/UniBinary/audio_summarizer/issues",
    },
)