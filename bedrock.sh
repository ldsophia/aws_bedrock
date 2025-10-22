# 准备目录
mkdir -p ~/layer-bedrock-agentcore/python
cd ~/layer-bedrock-agentcore

# 升级 pip 并安装 SDK 到 python/ 目录
python3.12 -m pip install --upgrade pip
pip3.12 install --no-cache-dir bedrock-agentcore -t python/

# 可选：strip .so 以减小体积（若存在本地编译依赖）
(command -v strip >/dev/null 2>&1 && find python -name '*.so' -exec strip -s {} +) || true

# 打包
zip -r9 layer-bedrock-agentcore-py312.zip python

aws s3 cp layer-bedrock-agentcore-py312.zip s3://<你的桶>/layers/layer-bedrock-agentcore-py312
