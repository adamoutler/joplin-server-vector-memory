# SafeSkill Registration and Certification

To register your package (like `dash`) with the SafeSkill registry and link your scan results upstream to safeskill.dev, you simply need to append the `--share` flag to your `skillsafe scan` command.

## How to Scan and Certify

Run the scan locally or in your CI/CD pipeline with the `--share` flag:

```bash
npx --yes skillsafe scan . --share
```

**What happens:**
1. SafeSkill performs its security and prompt-injection scan.
2. The results are uploaded directly to the `safeskill.dev` registry.
3. The command outputs a shareable URL verifying the scan results.
4. Your package's public badge is automatically updated to reflect the latest scan score.

## Adding the Badge

Once you have pushed a scan using `--share`, you can display the dynamic badge in your `README.md` using the standard Markdown syntax:

```markdown
[![SafeSkill](https://safeskill.dev/api/badge/your-package-name)](https://safeskill.dev/scan/your-package-name)
```

*(Ensure you replace `your-package-name` with the exact package name defined in your `package.json` or manifest.)*
