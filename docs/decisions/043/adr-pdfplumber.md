# ADR：为主披露 PDF 引入 pdfplumber 坐标抽取

## 决定

将 `pdfplumber==0.11.10` 作为开发依赖，用于从已跟踪的主披露 PDF 提取单词坐标，生成
离线 fixture 的 bbox 索引，并将数值型 PDF Evidence 的定位持久化为
`page,x0,top,x1,bottom`。既有 `pypdf` 继续负责稳定的纯文本 fixture 内容，不替换其余
provider 的文本解码路径。

## 依据与范围

`pypdf` 只提供文本，不能为财务表格中的数值提供版面锚点；而 `pdfplumber` 提供字符、单词
及表格抽取能力。采用它只解决机器生成 PDF 的坐标定位，不引入 OCR、Docling、Pandera 或
MuPDF。

- 来源：<https://pypi.org/project/pdfplumber/>
- 版本：`0.11.10`，精确锁定于 `pyproject.toml` 的 `dev` extra；默认离线运行不导入它
- 许可证：MIT；仓库 LICENSE 保留原作者 Jeremy Singer-Vine 的署名与许可文本
- 间接依赖：由受锁定的 pip 安装解析；完整环境由项目 `.venv` 的 editable install 验证

## 回滚

删除该依赖与 `bbox_index` 生成逻辑即可回到 `pypdf` 文本 fixture。此回滚会使新的 bbox
守卫失败，不能作为绕过解析问题的手段。
