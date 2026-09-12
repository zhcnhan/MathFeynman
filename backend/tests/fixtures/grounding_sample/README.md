# 接地审计样本（R37 教材锚定审计用）

这份目录是 **R37 教材锚定审计**（`backend/tests/audit_material_binding.py`）**固定的输入样本**。
它跟 `content/` 无关、也不是内容治理载体：`content/` 里放的是**当前生效的学科内容**，
这里放的是**一份不会变的审计样本**，用来让"讲解与题目必须有教材字面依据"这条质量尺子
在任何一台机器、任何一个 clone 上都能**逐位复现**。

## 这份样本是什么

三件东西（原本是用户那份数学教材 + 由它生成的两个内容节点）：

- `materials/researchgate-17551026c7.md`
  —— 用户上传的那份 `_researchgate` 教材（约 27.2 万字，R37 判定的"教材正文"）。
- `stages/node_s-f2decfcf.u01_auto.md`、`stages/node_s-f2decfcf.u02_auto.md`
  —— 由这份教材生成的**两个内容节点**（含讲解正文、`taught_facts` 声明、练习及 `basis.quote`）。
  审计就逐个检查这两份文件里的引文能不能在教材正文里**逐字**找到。

## 它从哪来

- 来源：`R61` 那一轮留下的完整内容根快照 `.runtime/r61_live/content/`，
  取其中的 `stages/s-f2decfcf/`（2 个节点）与 `subjects/s-f2decfcf/materials/researchgate-17551026c7.md`（1 份教材）。
- 为什么必须搬进来：`.runtime/` 是 `.gitignore` 的（一 clone 就没有），
  而 R61 之后用户把 `s-f2decfcf` 这门学科**自己删掉了** —— 留在运行期目录里
  就等于"换台机器谁也复现不出来"。上一批同事就因为随手挑样本得出过相反结论。
- **文件内容与来源快照逐字节一致**，没有做任何改写、清洗或重新生成。

## 怎么跑（在仓库根目录直接复制粘贴）

```powershell
.venv\Scripts\python.exe backend/tests/audit_material_binding.py --dir backend/tests/fixtures/grounding_sample/stages --material backend/tests/fixtures/grounding_sample/materials/researchgate-17551026c7.md
```

（`bash` / macOS / Linux 把 `.venv\Scripts\python.exe` 换成 `.venv/bin/python` 即可；
命令里**不需要也不应该出现 `.runtime/`**。若 `.venv` 没建好，用任意一个装了 `PyYAML` 的 Python 3.11+ 也行。）

这条命令**只读盘上的文件、不联网、不调用模型、不写任何东西**，退出码 0 = 内容与教材有字面接地。

## 期望读数（这四条就是判据，**不许放宽也不许收紧**）

- `taught_facts` 命中教材：**17/17**
- `basis.quote` 命中教材：**6/6**
- 讲解句子（≥12 字）整句命中教材：**9/83**
- 讲解句内含教材逐字片段（≥12 字）：**37/83**

⚠️ 后两条**偏低是正常的**：S3 允许讲解"换措辞/举例/类比"，所以"整句照抄"不是硬要求；
「含逐字片段」才反映"这句话是从教材演绎出来的"。审计的判据、阈值、口径写在
`backend/tests/audit_material_binding.py` 里，**改本样本不许顺手改它**。
