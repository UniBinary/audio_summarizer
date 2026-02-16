import json
import argparse
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Union

# 导入工具类
try:
    from .utils import (
        AVFinder,
        AudioExtractor,
        OSSUploader,
        AudioTranscriber,
        TextSummarizer
    )
except ImportError:
    # 如果相对导入失败，尝试绝对导入
    from utils import (
        AVFinder,
        AudioExtractor,
        OSSUploader,
        AudioTranscriber,
        TextSummarizer
    )

def summarize_cli():
    """
    该函数负责解析命令行参数并调用 summarize() 函数执行总结流程
    请勿在Python中调用此函数，该函数可通过命令行命令 audiosummarizer 或 sumaudio 传入参数调用（两个命令效果一样，只是别名）
    若想在Python中调用，请直接调用 summarize() 函数并传入相应参数
    """
    parser = argparse.ArgumentParser(description='音频总结工具 - 从音视频文件中提取音频、转文字并总结')
    parser.add_argument('--config-file',required=True, help=
"""配置字典，包含以下参数：
- bucket_name: 阿里云OSS存储桶名
- bucket_endpoint: 阿里云OSS存储桶endpoint
- access_key_id: 阿里云access key ID
- access_key_secret: 阿里云access key secret
- funasr_api_key: Fun-ASR模型API key
- deepseek_api_key: Deepseek模型API key
- ffmpeg_path: ffmpeg可执行文件路径（若想使用PATH中的ffmpeg，填写"ffmpeg"即可）
- ffprobe_path: ffprobe可执行文件路径（若想使用PATH中的ffprobe，填写"ffprobe"即可）""")
    parser.add_argument('--input-dir', required=True,
                        help='需要处理的包含音视频文件的目录的路径')
    parser.add_argument('--output-dir', required=True,
                        help='总结输出文件夹路径')
    parser.add_argument('--processes', type=int, default=1,
                        help='同时处理的进程数，默认为1')
    parser.add_argument('--audio-only', action='store_true',
                        help='如果设置，则不提取视频音轨，建议在输入文件夹中只有音频时设置。否则会消耗额外的OSS空间导致成本上升。')
    
    args = parser.parse_args()
    
    logger = _setup_logger(args.output_dir)

    # 从配置文件读取参数
    try:
        with open(args.config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.error(f"配置文件 {args.config_file} 未找到")
        exit(1)
    except Exception as e:
        logger.error(f"读取配置文件失败: {e}")
        exit(1)
    
    summarize(
        config=config,
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        processes=args.processes,
        audio_only=args.audio_only,
        logger=logger
    )



def summarize(config: dict[str, str],
              input_dir: Union[str, Path],
              output_dir: Union[str, Path],
              processes: int = 1,
              audio_only: bool = False,
              logger: logging.Logger = None):
    """
    audio_summarizer的主函数
    
    :param config: 配置字典，包含以下参数（键、值全部为str）：
        - bucket_name: 阿里云OSS存储桶名
        - bucket_endpoint: 阿里云OSS存储桶endpoint
        - access_key_id: 阿里云access key ID
        - access_key_secret: 阿里云access key secret
        - funasr_api_key: Fun-ASR模型API key
        - deepseek_api_key: Deepseek模型API key
        - ffmpeg_path: ffmpeg可执行文件路径（若想使用PATH中的ffmpeg，填写"ffmpeg"即可）
        - ffprobe_path: ffprobe可执行文件路径（若想使用PATH中的ffprobe，填写"ffprobe"即可）
    :type config: dict
    :param input_dir: 需要处理的包含音视频文件的目录的路径
    :type input_dir: str
    :param output_dir: 总结输出文件夹路径
    :type output_dir: str
    :param processes: 同时处理的进程数，默认为1
    :type processes: int
    :param audio_only: 默认为False，如果设置为True，则不提取视频音轨，建议在输入文件夹中只有音频时设置。否则会消耗额外的OSS空间导致成本上升。
    :type audio_only: bool or None
    :param logger: 可选的logger实例，如果未给出，将在函数内部创建一个新的logger
    :type logger: logging.Logger or None
    """

    # 转换为Path对象
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    
    # 创建中间目录（使用时间戳避免冲突）
    interm_dir = output_dir / "intermediates" / datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 设置logger
    if logger is None:
        logger = _setup_logger(output_dir)
    
    try:
        bucket_name = config["bucket_name"]
        bucket_endpoint = config["bucket_endpoint"]
        access_key_id = config["bucket_access_key_id"]
        access_key_secret = config["bucket_access_key_secret"]
        funasr_api_key = config["funasr_api_key"]
        deepseek_api_key = config["deepseek_api_key"]
        ffmpeg_path = Path(config["ffmpeg_path"])
        ffprobe_path = Path(config["ffprobe_path"])
    except KeyError as e:
        logger.error(f"配置文件缺少必要的参数: {e}")
        exit(1)
    except Exception as e:
        logger.error(f"读取配置文件失败: {e}")
        exit(1)

    # 创建目录
    interm_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 验证输入目录
    if not input_dir.exists() or not input_dir.is_dir():
        logger.error(f"输入目录 {input_dir} 不存在或不是一个目录。")
        exit(1)
    
    logger.info("=" * 60)
    logger.info("开始音频总结流程")
    logger.info("=" * 60)
    logger.info(f"输入目录: {input_dir}")
    logger.info(f"输出目录: {output_dir}")
    logger.info(f"中间目录: {interm_dir}")
    logger.info(f"进程数: {processes}")
    logger.info(f"仅音频模式: {audio_only}")
    
    # 步骤1: 寻找音视频文件
    logger.info("\n" + "=" * 60)
    logger.info("步骤1: 寻找音视频文件")
    logger.info("=" * 60)
    
    input_json = interm_dir / "inputs.json"
    finder = AVFinder(input_dir, input_json, logger)
    if not finder.find_and_save():
        logger.error("寻找音视频文件失败")
        exit(1)
    
    # 步骤2: 提取音频（如果不是仅音频模式）
    if not audio_only:
        logger.info("\n" + "=" * 60)
        logger.info("步骤2: 提取音频")
        logger.info("=" * 60)
        
        audio_dir = interm_dir / "audios"
        audio_json = interm_dir / "audios.json"
        
        extractor = AudioExtractor(
            input_json=input_json,
            output_json=audio_json,
            audio_dir=audio_dir,
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
            num_processes=processes,
            logger=logger
        )
        
        if not extractor.process_videos():
            logger.error("提取音频失败")
            exit(1)
    else:
        # 如果是仅音频模式，直接复制输入JSON到音频JSON
        audio_json = interm_dir / "audios.json"
        shutil.copy2(input_json, audio_json)
        logger.info("仅音频模式，跳过音频提取步骤")
    
    # 检查是否需要OSS上传和API调用
    if not (bucket_name and bucket_endpoint and access_key_id and access_key_secret and funasr_api_key and deepseek_api_key):
        logger.warning("\n缺少必要的API密钥或OSS配置，跳过后续步骤")
        logger.warning("请提供以下参数:")
        logger.warning("  --bucket-name, --bucket-endpoint")
        logger.warning("  --access-key-id, --access-key-secret")
        logger.warning("  --funasr-api-key, --deepseek-api-key")
        logger.warning("或使用 --config-file 指定配置文件")
        logger.info("\n已完成本地处理，结果保存在:")
        logger.info(f"  输入文件列表: {input_json}")
        logger.info(f"  音频文件列表: {audio_json}")
        exit(0)
    
    # 步骤3: 上传音频到OSS
    logger.info("\n" + "=" * 60)
    logger.info("步骤3: 上传音频到OSS")
    logger.info("=" * 60)
    
    oss_json = interm_dir / "oss_urls.json"
    uploader = OSSUploader(
        input_json=audio_json,
        output_json=oss_json,
        bucket_name=bucket_name,
        bucket_endpoint=bucket_endpoint,
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        num_processes=processes,
        logger=logger
    )
    
    if not uploader.upload_files():
        logger.error("上传音频到OSS失败")
        exit(1)
    
    # 步骤4: 音频转文字
    logger.info("\n" + "=" * 60)
    logger.info("步骤4: 音频转文字")
    logger.info("=" * 60)
    
    text_dir = interm_dir / "texts"
    text_json = interm_dir / "texts.json"
    transcriber = AudioTranscriber(
        input_json=oss_json,
        output_json=text_json,
        text_dir=text_dir,
        model_api_key=funasr_api_key,
        num_processes=processes,
        logger=logger
    )
    
    if not transcriber.transcribe_audio():
        logger.error("音频转文字失败")
        exit(1)
    
    # 步骤5: 总结文字
    logger.info("\n" + "=" * 60)
    logger.info("步骤5: 总结文字")
    logger.info("=" * 60)
    
    summary_dir = output_dir / "summaries"
    summary_json = interm_dir / "summaries.json"
    summarizer = TextSummarizer(
        input_json=text_json,
        output_json=summary_json,
        summary_dir=summary_dir,
        model_api_key=deepseek_api_key,
        num_processes=processes,
        origin_json=input_json,  # 添加原视频路径
        logger=logger
    )
    
    if not summarizer.summarize_texts():
        logger.error("总结文字失败")
        exit(1)
    
    # 完成
    logger.info("\n" + "=" * 60)
    logger.info("音频总结流程完成!")
    logger.info("=" * 60)
    logger.info(f"总结文件保存在: {summary_dir}")
    logger.info(f"中间文件保存在: {interm_dir}")
    logger.info(f"日志文件: {output_dir / 'audio_summarizer.log'}")
    
    # 显示总结文件列表
    summary_files = list(summary_dir.glob("*.md"))
    if summary_files:
        logger.info(f"\n生成 {len(summary_files)} 个总结文件:")
        for summary_file in sorted(summary_files):
            logger.info(f"  {summary_file.name}")

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

if __name__ == "__main__":
    summarize()  # 触发命令行参数解析