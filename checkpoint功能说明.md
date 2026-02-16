# Checkpoint功能实现说明

## 功能需求
在`main.py`中实现checkpoint功能：
1. 在程序开始时在`output_dir`中创建一个文件，名字叫`checkpoint.txt`，里面只放一个数字，初始值为0
2. 每成功执行完一个步骤后就将里面的数字加一
3. 在每次程序开始执行时先检查`output_dir`中有没有`checkpoint.txt`，如果有，就从里面的数字对应的步骤开始处理

## 实现方案

### 1. 步骤定义
定义了7个步骤状态：
```python
STEP_INIT = 0          # 初始状态
STEP_FIND_FILES = 1    # 步骤1: 寻找音视频文件
STEP_EXTRACT_AUDIO = 2 # 步骤2: 提取音频
STEP_UPLOAD_OSS = 3    # 步骤3: 上传到OSS
STEP_TRANSCRIBE = 4    # 步骤4: 音频转文字
STEP_SUMMARIZE = 5     # 步骤5: 总结文字
STEP_COMPLETE = 6      # 完成
```

### 2. Checkpoint文件操作函数

#### `_read_checkpoint(output_dir: Path) -> int`
- 读取checkpoint文件
- 如果文件不存在，返回0
- 如果读取失败（文件损坏等），返回0并记录警告

#### `_write_checkpoint(output_dir: Path, step: int)`
- 写入checkpoint文件
- 将步骤编号写入`checkpoint.txt`

#### `_update_checkpoint(output_dir: Path, logger: logging.Logger)`
- 更新checkpoint，将当前值加1
- 记录日志：`Checkpoint更新: {current_step} -> {new_step}`

### 3. 程序流程修改

#### 3.1 程序开始
```python
# 读取checkpoint
checkpoint = _read_checkpoint(output_dir)
logger.info(f"当前checkpoint: {checkpoint}")

# 创建中间目录（使用时间戳避免冲突）
# 如果checkpoint为0，创建新的中间目录；否则使用现有的中间目录
if checkpoint == 0:
    interm_dir = output_dir / "intermediates" / datetime.now().strftime("%Y%m%d_%H%M%S")
    interm_dir.mkdir(parents=True, exist_ok=True)
    # 初始化checkpoint为0
    _write_checkpoint(output_dir, 0)
else:
    # 查找最新的中间目录
    intermediates_dir = output_dir / "intermediates"
    if intermediates_dir.exists():
        # 获取所有中间目录并按时间排序
        interm_dirs = sorted([d for d in intermediates_dir.iterdir() if d.is_dir()])
        if interm_dirs:
            interm_dir = interm_dirs[-1]  # 使用最新的目录
            logger.info(f"使用现有的中间目录: {interm_dir}")
        else:
            logger.error("找不到中间目录，将从头开始")
            checkpoint = 0
            interm_dir = output_dir / "intermediates" / datetime.now().strftime("%Y%m%d_%H%M%S")
            interm_dir.mkdir(parents=True, exist_ok=True)
            _write_checkpoint(output_dir, 0)
```

#### 3.2 各个步骤的checkpoint检查
每个步骤都添加了checkpoint检查，只有当前checkpoint小于该步骤编号时才执行：

```python
# 步骤1: 寻找音视频文件
if checkpoint < STEP_FIND_FILES:
    # 执行步骤1...
    _update_checkpoint(output_dir, logger)
    checkpoint = STEP_FIND_FILES
else:
    logger.info("✓ 步骤1已完成，跳过")
```

#### 3.3 特殊情况处理

##### 仅音频模式
在仅音频模式下，步骤2（提取音频）被跳过，但仍需更新checkpoint：
```python
else:
    # 如果是仅音频模式，直接复制输入JSON到音频JSON
    if checkpoint < STEP_EXTRACT_AUDIO:
        shutil.copy2(input_json, audio_json)
        logger.info("仅音频模式，跳过音频提取步骤")
        _update_checkpoint(output_dir, logger)
        checkpoint = STEP_EXTRACT_AUDIO
    else:
        logger.info("✓ 仅音频模式步骤2已完成，跳过")
```

##### 缺少API密钥配置
当缺少必要的API密钥或OSS配置时，程序会跳过后续步骤并标记为完成：
```python
if not (bucket_name and bucket_endpoint and access_key_id and access_key_secret and funasr_api_key and deepseek_api_key):
    # ... 警告信息 ...
    # 标记为完成
    _write_checkpoint(output_dir, STEP_COMPLETE)
    exit(0)
```

#### 3.4 程序完成
程序完成后，将checkpoint标记为完成状态：
```python
# 标记为完成
_write_checkpoint(output_dir, STEP_COMPLETE)
```

### 4. 文件结构

#### checkpoint.txt文件格式
- 位置：`output_dir/checkpoint.txt`
- 内容：单个数字（0-6）
- 编码：UTF-8

#### 中间目录管理
- 当checkpoint为0时：创建新的中间目录（带时间戳）
- 当checkpoint不为0时：使用最新的现有中间目录
- 中间目录位置：`output_dir/intermediates/YYYYMMDD_HHMMSS/`

### 5. 使用示例

#### 第一次运行（从头开始）
```
当前checkpoint: 0
开始音频总结流程...
步骤1: 寻找音视频文件...
Checkpoint更新: 0 -> 1
步骤2: 提取音频...
Checkpoint更新: 1 -> 2
...
步骤5: 总结文字...
Checkpoint更新: 5 -> 6
音频总结流程完成!
```

#### 中途中断后重新运行（从步骤3开始）
```
当前checkpoint: 2
使用现有的中间目录: output/intermediates/20260216_180530
✓ 步骤1已完成，跳过
✓ 步骤2已完成，跳过
步骤3: 上传音频到OSS...
Checkpoint更新: 2 -> 3
步骤4: 音频转文字...
Checkpoint更新: 3 -> 4
步骤5: 总结文字...
Checkpoint更新: 4 -> 5
音频总结流程完成!
```

#### 已完成的任务重新运行
```
当前checkpoint: 6
使用现有的中间目录: output/intermediates/20260216_180530
✓ 步骤1已完成，跳过
✓ 步骤2已完成，跳过
✓ 步骤3已完成，跳过
✓ 步骤4已完成，跳过
✓ 步骤5已完成，跳过
音频总结流程完成!
```

### 6. 错误处理

#### checkpoint文件损坏
- 如果`checkpoint.txt`文件损坏或包含非数字内容，程序会从头开始
- 记录警告：`读取checkpoint文件失败，将从头开始: {e}`

#### 中间目录丢失
- 如果checkpoint不为0但找不到中间目录，程序会从头开始
- 记录错误：`找不到中间目录，将从头开始`

#### 写入失败
- 如果无法写入checkpoint文件，记录错误但继续执行
- 记录错误：`写入checkpoint文件失败: {e}`

### 7. 优势

1. **容错性**：程序中断后可以从断点继续，避免重复工作
2. **效率**：跳过已完成的步骤，节省时间和资源
3. **灵活性**：支持手动修改checkpoint值来控制执行流程
4. **透明性**：清晰的日志记录，便于调试和监控
5. **向后兼容**：不影响现有功能，新用户无需了解checkpoint机制

### 8. 注意事项

1. **手动修改checkpoint**：用户可以手动修改`checkpoint.txt`文件来控制从哪个步骤开始
2. **中间目录依赖**：checkpoint机制依赖于中间目录的存在，不要手动删除中间目录
3. **仅音频模式**：在仅音频模式下，步骤2的处理逻辑有所不同
4. **API配置检查**：缺少API配置时会直接标记为完成，跳过后续步骤

这样实现的checkpoint功能既满足了需求，又保持了代码的清晰性和可维护性。