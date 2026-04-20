---

# 农作物害虫识别系统上位机

## 简介

基于 YOLOv8x (试过v8s效果不怎么好)目标检测的农作物害虫实时识别上位机(识别软件部分)，配合 STM32 + ESP32-CAM 硬件平台，实现害虫的自动检测、记录与告警。

## 程序架构

```
三线程模型：
  StreamThread  → 拉取 ESP32-CAM MJPEG 视频流
  DetectThread  → YOLOv8x 推理，结果写入 SQLite
  主线程(Qt)    → UI 渲染、信号槽响应、用户交互

模块划分：
  ui/      主窗口 / 视频控件 / 告警面板 / 历史记录 / 设置对话框
  core/    流线程 / 推理线程 / 设备管理 / 截图管理
  db/      SQLite3 封装（检测记录 + 告警日志）
  config   默认参数 + settings.json 持久化
```

## 开发思路

硬件层由 STM32 触发告警,提示用户操作(ESP32CAM模块厂家已经预烧录了摄像头设定软件,直接通过按钮链接在浏览器打开设置界面就行了). ESP32-CAM 推流，上位机拉取 MJPEG 流，帧经队列传递至推理线程，检测结果通过 PyQt5 信号槽安全回传主线程渲染。

## 技术栈与工具

| 类别 | 选型 |
|------|------|
| 语言 | Python 3.10(高了会不兼容pyqt5) |
| GUI | PyQt5 5.15 |
| 推理 | Ultralytics YOLOv8x |
| 视频 | OpenCV |
| 存储 | SQLite3 |
| AI 代码辅助 | Claude Sonnet 4.6 Thinking |

## 更新日志
2026/4/21 识别软硬件联合调试完成(模型训练日志和结果:通过网盘分享的文件：train_and_test_result.zip链接: https://pan.baidu.com/s/1gZMOl6Xdo34eDmmx-f9XbA?pwd=6666 提取码: 6666)
2026/4/20 修复了UI界面无法正常显示视频流的问题(原因是cv2.VideoCapture拉流没法直接解析ESP32传输的格式,改为由urllib.request.urlopen读流)
