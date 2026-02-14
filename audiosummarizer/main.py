import argparse
import logging
from datetime import datetime
from pathlib import Path
from utils import *

def _setup_logger(output_dir: Path) -> logging.Logger:
    """配置logger"""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    # 避免重复添加handler
    if not logger.handlers:
        # 控制台handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        # 文件handler
        log_file = output_dir / "audio_summarizer.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger


def summarize(input_dir : str, output_dir : str, processes : int = 1, audio_only : bool = False):
    """
    audio_summarizer的主函数，提供两种调用方式：
    1. Python传入参数调用
    2. 命令行命令 audiosummarizer 或 sumaudio 传入参数调用（两个命令效果一样，只是别名）
    
    :param input_dir: 需要处理的包含音视频文件的目录的路径
    :type input_dir: str
    :param output_dir: 总结输出文件夹路径
    :type output_dir: str
    :param processes: 同时处理的进程数，默认为1
    :type processes: int
    :param audio_only: 如果设置，则不提取视频音轨，建议在输入文件夹中只有音频时设置。否则会消耗额外的OSS空间导致成本上升。
    :type audio_only: bool
    """

    if input_dir and output_dir:
        input_dir = Path(input_dir)
        output_dir = Path(output_dir)
    else:
        parser = argparse.ArgumentParser(description='音频总结主程序')
        parser.add_argument('--input-dir', required=True,
                            help='需要处理的包含音视频文件的目录的路径')
        parser.add_argument('--output-dir', required=True,
                            help='总结输出文件夹路径')
        parser.add_argument('--processes', type=int, default=1,
                            help='同时处理的进程数，默认为1')
        parser.add_argument('--audio-only', action='store_true',
                            help='如果设置，则不提取视频音轨，建议在输入文件夹中只有音频时设置。否则会消耗额外的OSS空间导致成本上升。')
        args = parser.parse_args()

        input_dir = args.input_dir
        output_dir = args.output_dir
        processes = args.processes
        audio_only = args.audio_only


    module_dir = Path(__file__).parent
    assets_path = module_dir / "assets"
    interm_dir = module_dir / "intermediates" / datetime.now().strftime("%Y%m%d_%H%M%S")
    ffmpeg_path = assets_path / "ffmpeg.exe"

    logger = _setup_logger(output_dir)
    interm_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not input_dir.exists() or not input_dir.is_dir():
        logger.error(f"输入目录 {input_dir} 不存在或不是一个目录。")
        exit(1) # 异常退出

    # 寻找音视频文件
    finder = AudioFinder(logger, input_dir, interm_dir)
    if not finder.find_and_save():
        exit(1) # 异常退出

    if not audio_only:
        # 提取音频
        extractor = AudioExtractor(
            logger=logger,
            ffmpeg_path=ffmpeg_path,
            output_dir=interm_dir / "audios",
            input_json=interm_dir / "audios.json",
            num_processes=processes
        )
        # 开始处理
        if not extractor.process_videos():
            exit(1) # 异常退出
