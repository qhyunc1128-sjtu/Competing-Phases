# Competing Phases V5.1 — MP Tasks API 字段修复

## 错误现象

打开“⑥ 高级核查”，选择 mp-1001113 后出现：

```
invalid fields requested: ['state']
```

原因：旧版 `fetch_task_audit()` 在 `mpr.materials.tasks.search()` 中请求 `state`，但 MP 当前的 Tasks API schema 没有该字段。

## 修复内容

- 删除 `state` 查询字段与结果列。
- 增加 Tasks API 支持的 `calc_type`（计算类型）和 `completed_at`（完成时间）。
- 保留 task ID、关联材料 ID、run_type、task_type、raw energy/atom、POTCAR、U 参数等输出。
- 不更改主界面、其他 MP 检索方式，也不影响竞争相能量优化、★实验结构与全部 MP 相两套计算。

## GitHub / Streamlit Cloud 升级（只需要一个文件）

1. 打开 `https://github.com/qhyunc1128-sjtu/Competing-Phases`，切换到 `main` 分支。
2. 用该包提供的 `mp_backend.py` **覆盖仓库根目录**中的同名文件。不要上传外层文件夹。
3. 选择 Commit changes（提交），Streamlit 将触发更新。若仍显示旧界面/旧错误，可以 Reboot app。
4. 在网页的“⑥ 高级核查”重新选择 `mp-1001113` 并查询，查看 VASP Task 列表。

如果不方便覆盖，可在 GitHub 打开旧的 `mp_backend.py` 点击 Edit（铅笔），找到 `fetch_task_audit`：

```python
fields=['task_id', 'run_type', 'task_type', 'state', 'input', 'output'],
```

替换为：

```python
fields=['task_id', 'run_type', 'task_type', 'calc_type', 'completed_at', 'input', 'output'],
```

然后删除结果字典里的 `'state': _scalar(_value(d, 'state')),` 一行，保存提交；或一并替换为：

```python
'calc_type': _scalar(_value(d, 'calc_type')),
'completed_at': _scalar(_value(d, 'completed_at')),
```

## 测试

V5 原有 25 项离线/模拟接口测试通过，加入了“API 不允许 `state` 字段”的严格测试。**没有使用真实 API Key 联机访问用户数据；需要网站部署后做一次真实查询确认。**
