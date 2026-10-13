# 构建、下载与部署

## GitHub Actions 已有能力

`master` 的提交触发 [主线构建](https://github.com/nhh37740-glitch/ai-rag-platform/actions/workflows/build.yml)：准备环境、编译 Cython 模块、执行 Dockerfile 指定的测试、打包 ZIP，并上传到 **Actions Artifacts（保留 14 天）**。

**下载方法：** Actions → 成功的「主线构建」→ Artifacts。构建失败不能视为已有可下载发布包。

## 尚未接入的能力

- 当前 `build.yml` **不会**创建正式的 GitHub Release，也不会推送镜像到 GHCR。
- 当前 GitHub Actions **不会**自动将发布包/镜像部署到 VPS。
- Jenkins 仍存在独立验证与可选部署流程；不应混称为 Actions 自动部署。
- 合并 PR、生成 ZIP 和生产服务健康是不同的状态。

线上密钥、管理员初始化口令不能提交到仓库或 Wiki。生产发布和回滚需要独立验证服务器健康状态。

来源：[build.yml](https://github.com/nhh37740-glitch/ai-rag-platform/blob/master/.github/workflows/build.yml)、[Jenkinsfile](https://github.com/nhh37740-glitch/ai-rag-platform/blob/master/Jenkinsfile)、[Dockerfile](https://github.com/nhh37740-glitch/ai-rag-platform/blob/master/Dockerfile)。
