# cursor-skill-push-to-github

Cursor Agent Skill：在 Windows 上把当前项目发布到 GitHub。默认创建**私有**仓库。

部分网络无法对 `github.com:443` 执行 `git push`（连接被重置）。本技能改用 GitHub API 写入提交树，**不会**调用 `git push` 或 `gh repo create --push`。

## 安装

把本仓库复制为：

```text
%USERPROFILE%\.cursor\skills\push-to-github\
```

目录内必须有 `SKILL.md`。复制后对 Agent 说「推到 GitHub」即可。

## 依赖

- [Git for Windows](https://git-scm.com/download/win)
- [GitHub CLI](https://cli.github.com/)，并完成 `gh auth login`

Agent 新开的 shell 往往没有 Git / gh 的 PATH。先执行：

```powershell
. "$env:USERPROFILE/.cursor/skills/push-to-github/scripts/ensure-tools.ps1"
```

## 做什么

1. 如有需要则 `git init`
2. 检查并补全 `.gitignore`（排除密钥、日志、`.env`）
3. 本地 `git commit`（不修改 git config；缺身份时用当前 `gh` 登录名的 noreply 邮箱）
4. 没有 `origin` 时用 `gh repo create` 建仓（不加 `--push`）
5. 运行 [`scripts/publish-via-gh-api.py`](scripts/publish-via-gh-api.py)，通过 Contents API + Git Data API 把 HEAD 写到 `origin`

完整流程见 [SKILL.md](SKILL.md)，Windows 细节见 [reference.md](reference.md)。

## 硬限制

- 不运行 `git config` / `git push` / force-push
- 不删除 GitHub 仓库，不改已有 remote
- 不跳过 hooks
- 不提交密钥

## License

MIT
