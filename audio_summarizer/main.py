import argparse
import logging
from datetime import datetime
from pathlib import Path
from find_audios import AudioFinder
from audio_extractor import AudioExtractor

def setup_logger(output_dir: Path) -> logging.Logger:
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


def main():
    parser = argparse.ArgumentParser(description='音频总结主程序')
    parser.add_argument('--input', required=True,
                        help='需要处理的包含音视频文件的目录的路径')
    parser.add_argument('--output', required=True,
                        help='总结输出文件夹路径')
    parser.add_argument('--processes', type=int, default=1,
                        help='同时处理的进程数，默认为1')
    parser.add_argument('--audio-only', action='store_true',
                        help='如果设置，则不提取视频音轨，建议在输入文件夹中只有音频时设置。否则会消耗额外的OSS空间导致成本上升。')
    
    args = parser.parse_args()

    module_dir = Path(__file__).parent
    assets_path = module_dir / "assets"
    input_dir = Path(args.input)
    output_dir = Path(args.output)
    interm_dir = output_dir / "intermediates" / datetime.now().strftime("%Y%m%d_%H%M%S")
    ffmpeg_path = assets_path / "ffmpeg.exe"
    processes = args.processes

    logger = setup_logger(output_dir)
    interm_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not input_dir.exists() or not input_dir.is_dir():
        logger.error(f"输入目录 {input_dir} 不存在或不是一个目录。")
        exit(1) # 异常退出

    # 寻找音视频文件
    finder = AudioFinder(logger, input_dir, interm_dir)
    if not finder.find_and_save():
        exit(1) # 异常退出

    if not args.audio_only:
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
    
    


if __name__ == '__main__':
    main()