# 智能域名生成器

根据用户描述，利用 OpenAI 生成与内容强相关、有故事、有内涵的域名，并自动检测可注册性。

## 安装

```bash
pip install -r requirements.txt
```

## 启动

```bash
python app.py
```

浏览器访问 http://127.0.0.1:5000/

## 使用

1. 点击右上角"⚙ 设置"，填入 OpenAI API Key（仅存本地 localStorage）
2. 在主界面填写项目描述、选择 TLD 后缀、调整长度与数量
3. 点击"生成域名"，等待结果

## 环境变量

暂不支持环境变量配置，所有 API Key 通过前端设置输入并保存到浏览器 localStorage。