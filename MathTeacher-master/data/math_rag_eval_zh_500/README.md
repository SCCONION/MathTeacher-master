# MathTutor 中文数学 RAG 检索评测集（Synthetic v1）

## 1. 用途

这是为 MathTutor 项目构建的**项目内中文数学检索评测集**，用于比较：

- BM25
- BGE + FAISS
- Hybrid RRF
- （可选）Hybrid RRF + CRAG 相似度过滤

它不是公开 benchmark，也不是从真实学生数据采集得到的数据。简历或面试中应称为：

> 自建中文数学 RAG 检索评测集 / 项目内检索消融集

不要称为“公开数据集”或“BRIGHT 官方 benchmark”。

## 2. 数据规模

- Query：50 条
- Corpus：500 条
- Gold document：50 条
- Hard negative：150 条
- Background negative：300 条
- 数学主题：10 类，每类 5 个 Query
- 每个 Query 恰好有 1 个 gold document

Query 类型分布：

- direct：15
- semantic：20
- formula：15

覆盖主题：

二次函数、方程与不等式、三角函数、数列、概率统计、导数、积分、平面几何、向量、排列组合。

## 3. 文件

- `queries.jsonl`：查询文本与题型标签
- `corpus.jsonl`：500 条候选知识片段
- `qrels.tsv`：Query 到 Gold Document 的相关性标注
- `dataset_stats.json`：数据统计
- `evaluate_retrieval.py`：BM25 / FAISS / Hybrid RRF 评测脚本

## 4. 为什么加入 Hard Negative

Hard Negative 会故意与 Query 共享数学主题、术语或邻近知识点，但不直接回答问题。

例如 Query 问“二次函数顶点公式”，负样本可能谈“二次函数判别式”或“顶点概念但不给公式”。

这样可以避免所有方法都轻松达到接近 100%，更适合测试：

- BM25 是否过度依赖关键词；
- FAISS 是否能理解同义表达；
- Hybrid 是否利用稀疏与稠密检索的互补性。

## 5. 指标解释

本数据集每个 Query 只有一个 Gold Document，因此：

- Recall@1 = Gold 是否排在第 1 名的平均值
- Recall@5 = Gold 是否进入前 5 名的平均值
- Recall@10 = Gold 是否进入前 10 名的平均值

严格地说，在“每个 Query 只有一个相关文档”的设定下，它们也等同于 Hit@1 / Hit@5 / Hit@10。

MRR@10 更关注 Gold 的具体排名位置：

- 第 1 名：1
- 第 2 名：1/2
- 第 3 名：1/3
- 超出 Top-10：0

最后对所有 Query 求平均。

## 6. 推荐实验写法

先保持完全相同的 50 Query / 500 Corpus，只替换检索方法：

1. BM25-bigram
2. BGE-large-zh-v1.5 + FAISS
3. Hybrid RRF
4. Hybrid RRF + CRAG（可选）

建议报告：

- Recall@1
- Recall@5
- Recall@10
- MRR@10
- Avg latency

## 7. 简历表述模板

实际跑出结果后再填数字：

> 构建 50 Query / 500 Document 中文数学检索评测集，引入同义改写、公式符号查询及 Hard Negative 场景，对 BM25、BGE+FAISS 与 Hybrid RRF 进行消融评测；Hybrid RRF 的 Recall@5 相比纯 FAISS 提升 X.X 个百分点。

注意：`X.X` 必须来自真实运行结果，不能预填或虚构。

## 8. 数据局限

这是小规模、人工构造的工程评测集，适合项目消融与回归测试，但不能替代大规模公开 benchmark。若后续需要更有说服力的结果，可以再增加：

- 公开中文通用检索 benchmark；
- 公开数学 retrieval benchmark；
- 真实知识库/真实用户问题的人工标注集。
