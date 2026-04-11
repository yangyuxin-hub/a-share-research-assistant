直接ccswitch切换

# 启用api计费

$env:ANTHROPIC_BASE_URL = "https://luckycodecc.cn/claude"
$env:ANTHROPIC_API_KEY = "sk-yIvRp1ndxpNBV2fXMMJzM4MphHqIIKVZj33BLX5X6E9Db3LJ"

/logout

[System.Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "User")
[System.Environment]::GetEnvironmentVariable("ANTHROPIC_BASE_URL", "User")

[Environment]::SetEnvironmentVariable("ANTHROPIC_BASE_URL", "https://luckycodecc.cn/claude", "User")
[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "sk-yIvRp1ndxpNBV2fXMMJzM4MphHqIIKVZj33BLX5X6E9Db3LJ", "User")


# 移除api计费

[System.Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", $null, "User")
[System.Environment]::SetEnvironmentVariable("ANTHROPIC_BASE_URL", $null, "User")
