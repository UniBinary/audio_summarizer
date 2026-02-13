#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音频转文本程序 - 使用FunASR大模型
功能：将音频文件上传到阿里云OSS，通过FunASR API转换为文本

输出格式：
<speaker_id+1>: <句子>

示例：
1: 你好！
2: 你好，我们今天干点什么呢？
1: 来一起拼乐高吧！
2: 好。

说明：
- speaker_id从0开始，+1使其从1开始
- 按时间顺序排列句子
- 支持多说话人对话分离
"""

import os
import sys
import json
import argparse
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Dict, Tuple
import oss2
from http import HTTPStatus
from dashscope.audio.asr import Transcription
from urllib import request
import dashscope


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('audio2summary.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class Audio2Summary:
    def __init__(self, config_path: str = "D:\\QwenASR\\config.json"):
        """初始化配置"""
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # 以下为北京地域url
        self.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'
        # 读取 API key，优先从配置文件，其次从环境变量
        self.api_key = config["model-api-key"]

        self.bucket_name = config["bucket-name"]
        self.endpoint = config["bucket-endpoint"]
        self.access_key_id = config["bucket-access-key-id"]
        self.access_key_secret = config["bucket-access-key-secret"]
        
        # 初始化OSS客户端
        auth = oss2.Auth(self.access_key_id, self.access_key_secret)
        self.bucket = oss2.Bucket(auth, self.endpoint, self.bucket_name)
        
        # FunASR API端点
        self.funasr_url = "https://api.funasr.com/v1/audio/transcriptions"
        
        logger.info(f"初始化完成，使用存储桶: {self.bucket_name}")
    
    def upload_to_oss(self, file_path: str, object_name: str) -> str:
        """上传文件到OSS并返回URL"""
        try:
            if self.bucket.object_exists(object_name):
                logger.info(f"文件已存在，跳过上传: {object_name}")
                url = self.bucket.sign_url('GET', object_name, 86400)  # URL有效期1天
                return url
            logger.info(f"上传文件: {file_path} -> {object_name}")
            self.bucket.put_object_from_file(object_name, file_path)
            
            # 生成可访问的URL
            url = self.bucket.sign_url('GET', object_name, 86400)  # URL有效期1天
            logger.info(f"上传成功: {url}")
            return url
        except Exception as e:
            logger.error(f"上传失败 {file_path}: {e}")
            raise
    
    def transcribe_audio(self, audio_urls: List[str]) -> List[Dict]:
        """调用FunASR API进行语音识别，返回处理后的结果列表"""

        dashscope.base_http_api_url = self.base_http_api_url
        dashscope.api_key = self.api_key

        task_response = Transcription.async_call(
            model='fun-asr',
            file_urls=audio_urls,
            language_hints=['zh',],
            diarization_enabled=True,
        )

        transcription_response = Transcription.wait(task=task_response.output.task_id)

        processed_results = [] 
        if transcription_response.status_code == HTTPStatus.OK:
            for transcription in transcription_response.output['results']:
                if transcription['subtask_status'] == 'SUCCEEDED':
                    url = transcription['transcription_url']
                    result_data = json.loads(request.urlopen(url).read().decode('utf8'))
                    
                    # 处理结果，生成格式化的字符串
                    result_str = self._format_transcription_result(result_data)
                    processed_results.append(result_str)
                else:
                    logger.error(f'转录失败: {transcription}')
                    processed_results.append("")  # 失败时返回空字符串
        else:
            logger.error(f'Fun-ASR API错误: {transcription_response.output.message}')
            # 返回与音频URL数量相同的空字符串列表
            processed_results = [""] * len(audio_urls)
        
        return processed_results
    
    def _format_transcription_result(self, result_data: Dict) -> str:
        """
        格式化转录结果为指定的字符串格式
        
        格式要求:
        <speaker_id+1>: <句子>
        
        示例:
        1: 你好！
        2: 你好，我们今天干点什么呢？
        1: 来一起拼乐高吧！
        2: 好。
        """
        try:
            transcripts = result_data.get("transcripts", [])
            if not transcripts:
                return ""
            
            formatted_lines = []
            
            for transcript in transcripts:
                sentences = transcript.get("sentences", [])
                if not sentences:
                    continue
                
                # 按时间顺序排序句子
                sorted_sentences = sorted(sentences, key=lambda x: x.get("begin_time", 0))
                
                for sentence in sorted_sentences:
                    speaker_id = sentence.get("speaker_id", 0)
                    text = sentence.get("text", "").strip()
                    
                    if text:  # 只添加非空文本
                        # speaker_id从0开始，+1使其从1开始
                        formatted_line = f"{speaker_id + 1}: {text}"
                        formatted_lines.append(formatted_line)
            
            # 将所有行用换行符连接
            result_str = "\n".join(formatted_lines)
            return result_str
            
        except Exception as e:
            logger.error(f"格式化转录结果失败: {e}")
            return ""
    
    def process_batch(self, file_infos: List[Tuple[str, str, str]], output_dir: str) -> Dict[str, str]:
        """处理一批文件"""
        results = {}
        
        # 分批处理，每批最多100个文件
        batch_size = 100
        for i in range(0, len(file_infos), batch_size):
            batch = file_infos[i:i+batch_size]
            audio_urls = []
            file_mapping = {}  # 映射URL到文件名
            
            # 上传当前批次的所有文件
            for local_path, object_name, filename in batch:
                try:
                    url = self.upload_to_oss(local_path, object_name)
                    audio_urls.append(url)
                    file_mapping[url] = filename.replace(".mp3", "")  # 去掉扩展名
                except Exception as e:
                    logger.error(f"跳过文件 {filename}: {e}")
                    continue
            
            if not audio_urls:
                logger.warning(f"批次 {i//batch_size + 1} 没有成功上传的文件")
                continue
            
            logger.info(f"批次 {i//batch_size + 1}: 处理 {len(audio_urls)} 个音频文件")
            
            # 调用FunASR API
            try:
                transcription_results = self.transcribe_audio(audio_urls)
                
                # 将结果映射回文件名
                for url, result_str in zip(audio_urls, transcription_results):
                    filename = file_mapping.get(url)
                    if filename and result_str:
                        results[filename] = result_str
                        logger.info(f"  文件 {filename}: 转录成功，{len(result_str.splitlines())} 个对话片段")
                    elif filename:
                        results[filename] = ""
                        logger.warning(f"  文件 {filename}: 转录结果为空")
                        
            except Exception as e:
                logger.error(f"批次 {i//batch_size + 1} API调用失败: {e}")
                # 为失败的批次添加空结果
                for url in audio_urls:
                    filename = file_mapping.get(url)
                    if filename:
                        results[filename] = ""
        
        return results
    
    def save_results(self, results: Dict[str, str], output_dir: str):
        """保存转录结果到文件"""
        for filename, text in results.items():
            output_path = os.path.join(output_dir, f"{filename}.txt")
            try:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                logger.info(f"保存结果: {output_path}")
            except Exception as e:
                logger.error(f"保存文件失败 {output_path}: {e}")
    
    def get_file_list(self, input_dir: str, from_num: int, to_num: int, skip_nums: List[int]) -> List[Tuple[str, str, str]]:
        """获取要处理的文件列表（类方法）"""
        files = []
        
        for num in range(from_num, to_num + 1):
            if num in skip_nums:
                logger.info(f"跳过文件: {self.format_number(num)}.mp3")
                continue
                
            filename = f"{self.format_number(num)}.mp3"
            file_path = os.path.join(input_dir, filename)
            
            if os.path.exists(file_path):
                object_name = f"audio_transcription/{filename}"
                files.append((file_path, object_name, filename))
            else:
                logger.warning(f"文件不存在: {file_path}")
        
        logger.info(f"找到 {len(files)} 个文件需要处理")
        return files

    def format_number(self, num: int) -> str:
        """将数字格式化为3位数字符串，如 1 -> '001'"""
        return f"{num:03d}"

def split_list(lst: List, n: int) -> List[List]:
    """将列表分成n个大致相等的部分"""
    k, m = divmod(len(lst), n)
    return [lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]

def main():
    parser = argparse.ArgumentParser(description="音频转文本程序 - 使用FunASR大模型")
    parser.add_argument("--input-dir", default="D:\\QwenASR\\audios", 
                        help="输入文件夹路径，默认为 D:\\QwenASR\\audios")
    parser.add_argument("--output-dir", default="D:\\QwenASR\\audio_text", 
                        help="输出文件夹路径，默认为 D:\\QwenASR\\audio_text")
    parser.add_argument("--processes", type=int, default=1, 
                        help="同时请求进程数，默认为1")
    parser.add_argument("--from-number", type=int, required=True, 
                        help="从第几号文件开始处理")
    parser.add_argument("--to-number", type=int, required=True, 
                        help="到第几号文件结束处理")
    parser.add_argument("--skip", type=int, nargs="*", default=[], 
                        help="跳过处理的文件编号（可多个）")
    parser.add_argument("--use-skip-file", action="store_true", help="use skip file")
    parser.add_argument("--skip-file", type=str, default=r"D:\QwenASR\skips.json",
                        help="skip file path")
    
    args = parser.parse_args()
    
    # 验证参数
    if args.from_number > args.to_number:
        logger.error("起始编号不能大于结束编号")
        sys.exit(1)
    
    if args.processes < 1:
        logger.error("进程数必须大于0")
        sys.exit(1)
    
    # 确保输出目录存在
    os.makedirs(args.output_dir, exist_ok=True)
    
    if args.use_skip_file:
        with open(args.skip_file, 'r', encoding="utf-8") as skip_file:
            skips = json.load(skip_file)
    else:
        skips = args.skip

    logger.info(f"开始处理: 文件 {args.from_number} 到 {args.to_number}")
    logger.info(f"跳过文件: {skips}")
    logger.info(f"使用进程数: {args.processes}")

    # 初始化转录器（现在在类中包含文件列表方法）
    transcriber = Audio2Summary()

    # 获取文件列表
    files = transcriber.get_file_list(args.input_dir, args.from_number, args.to_number, skips)

    if not files:
        logger.warning("没有找到需要处理的文件")
        return
    
    # 将文件分配给各个进程
    file_chunks = split_list(files, args.processes)
    
    all_results = {}
    
    # 使用进程池处理
    with ProcessPoolExecutor(max_workers=args.processes) as executor:
        future_to_chunk = {}
        
        for i, chunk in enumerate(file_chunks):
            if chunk:  # 只提交非空的任务
                future = executor.submit(transcriber.process_batch, chunk, args.output_dir)
                future_to_chunk[future] = i
        
        # 收集结果
        for future in as_completed(future_to_chunk):
            chunk_index = future_to_chunk[future]
            try:
                results = future.result()
                all_results.update(results)
                logger.info(f"进程 {chunk_index + 1} 完成，处理了 {len(results)} 个文件")
            except Exception as e:
                logger.error(f"进程 {chunk_index + 1} 执行失败: {e}")
    
    # 保存所有结果
    transcriber.save_results(all_results, args.output_dir)
    
    logger.info(f"处理完成！共处理 {len(all_results)} 个文件")
    logger.info(f"结果保存在: {args.output_dir}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("用户中断程序")
        sys.exit(0)
    except Exception as e:
        logger.error(f"程序执行失败: {e}")
        sys.exit(1)