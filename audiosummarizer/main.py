import json
import argparse
import logging
import shutil
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
    
    logger = _setup_logger(Path(args.output_dir) / "audio_summarizer.log")

    # 从配置文件读取参数
    try:
        with open(str(args.config_file), 'r', encoding='utf-8') as f:
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



def _read_checkpoint(output_dir: Path) -> int:
    """
    读取checkpoint文件
    
    Args:
        output_dir: 输出目录
        
    Returns:
        int: checkpoint值，如果文件不存在则返回0
    """
    checkpoint_file = output_dir / "checkpoint.txt"
    if checkpoint_file.exists():
        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                return int(content)
        except (ValueError, IOError) as e:
            logging.getLogger(__name__).warning(f"读取checkpoint文件失败，将从头开始: {e}")
            return 0
    return 0

def _write_checkpoint(output_dir: Path, step: int):
    """
    写入checkpoint文件
    
    Args:
        output_dir: 输出目录
        step: 步骤编号
    """
    checkpoint_file = output_dir / "checkpoint.txt"
    try:
        with open(checkpoint_file, 'w', encoding='utf-8') as f:
            f.write(str(step))
    except IOError as e:
        logging.getLogger(__name__).error(f"写入checkpoint文件失败: {e}")

def _update_checkpoint(output_dir: Path, logger: logging.Logger):
    """
    更新checkpoint，将当前值加1
    
    Args:
        output_dir: 输出目录
        logger: 日志记录器
    """
    current_step = _read_checkpoint(output_dir)
    new_step = current_step + 1
    _write_checkpoint(output_dir, new_step)
    logger.info(f"Checkpoint更新: {current_step} -> {new_step}")


def _ensure_dir(path: Path, logger: logging.Logger):
    """
    确保给定路径存在且为目录
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"创建目录 {path} 失败: {e}")
        exit(1)

# 步骤定义
STEP_INIT = 0          # 初始状态
STEP_FIND_FILES = 1    # 步骤1: 寻找音视频文件
STEP_EXTRACT_AUDIO = 2 # 步骤2: 提取音频
STEP_UPLOAD_OSS = 3    # 步骤3: 上传到OSS
STEP_TRANSCRIBE = 4    # 步骤4: 音频转文字
STEP_SUMMARIZE = 5     # 步骤5: 总结文字
STEP_COMPLETE = 6      # 完成

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
    :type input_dir: Union[str, Path]
    :param output_dir: 总结输出文件夹路径
    :type output_dir: Union[str, Path]
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
    log_file = output_dir / "audio_summarizer.log"
    
    # 设置logger
    if logger is None:
        logger = _setup_logger(log_file)
    
    # 读取checkpoint
    checkpoint = _read_checkpoint(output_dir)
    logger.info(f"当前checkpoint: {checkpoint}")
    
    interm_dir = output_dir / "intermediates"
    # 创建中间目录（使用时间戳避免冲突）
    # 如果checkpoint为0，创建新的中间目录；否则使用现有的中间目录
    if checkpoint == 0:
        _ensure_dir(interm_dir, logger)
        # 初始化checkpoint为0
        _write_checkpoint(output_dir, 0)
    else:
        if interm_dir.exists():
            logger.info(f"使用现有的中间目录: {interm_dir}")
        else:
            logger.warning("找不到中间目录，将从头开始")
            checkpoint = 0
            _ensure_dir(interm_dir, logger)
            _write_checkpoint(output_dir, 0)
    
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
    _ensure_dir(interm_dir, logger)
    _ensure_dir(output_dir, logger)
    
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
    if checkpoint < STEP_FIND_FILES:
        logger.info("=" * 60)
        logger.info("步骤1: 寻找音视频文件")
        logger.info("=" * 60)
        
        input_json = interm_dir / "inputs.json"
        finder = AVFinder(input_dir, input_json, log_file=log_file)
        if not finder.find_and_save():
            logger.error("寻找音视频文件失败")
            exit(1)
        
        _update_checkpoint(output_dir, logger)
        checkpoint = STEP_FIND_FILES
    else:
        logger.info("✓ 步骤1已完成，跳过")
        input_json = interm_dir / "inputs.json"
    
    # 步骤2: 提取音频（如果不是仅音频模式）
    audio_dir = interm_dir / "audios"
    audio_json = interm_dir / "audios.json"
    
    if not audio_only:
        if checkpoint < STEP_EXTRACT_AUDIO:
            logger.info("=" * 60)
            logger.info("步骤2: 提取音频")
            logger.info("=" * 60)
            
            extractor = AudioExtractor(
                input_json=input_json,
                output_json=audio_json,
                audio_dir=audio_dir,
                ffmpeg_path=ffmpeg_path,
                ffprobe_path=ffprobe_path,
                num_processes=processes,
                log_file=log_file
            )
            
            if not extractor.process_videos():
                logger.error("提取音频失败")
                exit(1)
            
            _update_checkpoint(output_dir, logger)
            checkpoint = STEP_EXTRACT_AUDIO
        else:
            logger.info("✓ 步骤2已完成，跳过")
    else:
        # 如果是仅音频模式，直接复制输入JSON到音频JSON
        if checkpoint < STEP_EXTRACT_AUDIO:
            shutil.copy2(input_json, audio_json)
            logger.info("仅音频模式，跳过音频提取步骤")
            _update_checkpoint(output_dir, logger)
            checkpoint = STEP_EXTRACT_AUDIO
        else:
            logger.info("✓ 仅音频模式步骤2已完成，跳过")
    
    # 步骤3: 上传音频到OSS
    oss_json = interm_dir / "oss_urls.json"
    
    if checkpoint < STEP_UPLOAD_OSS:
        logger.info("=" * 60)
        logger.info("步骤3: 上传音频到OSS")
        logger.info("=" * 60)
        
        uploader = OSSUploader(
            input_json=audio_json,
            output_json=oss_json,
            bucket_name=bucket_name,
            bucket_endpoint=bucket_endpoint,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            num_processes=processes,
            log_file=log_file
        )
        
        if not uploader.upload_files():
            logger.error("上传音频到OSS失败")
            exit(1)
        
        _update_checkpoint(output_dir, logger)
        checkpoint = STEP_UPLOAD_OSS
    else:
        logger.info("✓ 步骤3已完成，跳过")
    
    # 步骤4: 音频转文字
    text_dir = interm_dir / "texts"
    text_json = interm_dir / "texts.json"
    
    if checkpoint < STEP_TRANSCRIBE:
        logger.info("=" * 60)
        logger.info("步骤4: 音频转文字")
        logger.info("=" * 60)
        
        transcriber = AudioTranscriber(
            input_json=oss_json,
            output_json=text_json,
            text_dir=text_dir,
            model_api_key=funasr_api_key,
            num_processes=processes,
            log_file=log_file
        )
        
        if not transcriber.transcribe_audio():
            logger.error("音频转文字失败")
            exit(1)
        
        _update_checkpoint(output_dir, logger)
        checkpoint = STEP_TRANSCRIBE
    else:
        logger.info("✓ 步骤4已完成，跳过")
    
    # 步骤5: 总结文字
    summary_dir = output_dir / "summaries"
    summary_json = interm_dir / "summaries.json"
    
    if checkpoint < STEP_SUMMARIZE:
        logger.info("=" * 60)
        logger.info("步骤5: 总结文字")
        logger.info("=" * 60)
        
        summarizer = TextSummarizer(
            input_json=text_json,
            output_json=summary_json,
            summary_dir=summary_dir,
            model_api_key=deepseek_api_key,
            num_processes=processes,
            origin_json=input_json,
            log_file=log_file
        )
        
        if not summarizer.summarize_texts():
            logger.error("总结文字失败")
            exit(1)
        
        _update_checkpoint(output_dir, logger)
        checkpoint = STEP_SUMMARIZE
    else:
        logger.info("✓ 步骤5已完成，跳过")
    
    # 完成
    logger.info("=" * 60)
    logger.info("音频总结流程完成!")
    logger.info("=" * 60)
    logger.info(f"总结文件保存在: {summary_dir}")
    logger.info(f"中间文件保存在: {interm_dir}")
    logger.info(f"日志文件: {output_dir / 'audio_summarizer.log'}")
    
    # 显示总结文件列表
    summary_files = list(summary_dir.glob("*.md"))
    if summary_files:
        logger.info(f"生成 {len(summary_files)} 个总结文件:")
        for summary_file in sorted(summary_files):
            logger.info(f"  {summary_file.name}")
    
    # 标记为完成
    _write_checkpoint(output_dir, STEP_COMPLETE)

def _setup_logger(log_file: Path) -> logging.Logger:
    """配置logger"""
    logger = logging.getLogger("AudioSummarizer")
    logger.setLevel(logging.INFO)
    
    # 避免重复添加handler
    if not logger.handlers:
        # 控制台handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('[AudioSummarizer] %(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        # 文件handler
        _ensure_dir(log_file.parent, logger)  # 确保日志文件所在目录存在
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter('[AudioSummarizer] %(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger

if __name__ == "__main__":
    summarize()  # 触发命令行参数解析