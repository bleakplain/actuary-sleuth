"""记忆提取和画像更新 Prompt。"""

AUDIT_FACT_EXTRACTION_PROMPT = """\
请仅提取与保险产品审核相关的事实：产品名称、条款问题、定价疑虑、法规引用、免责分析、等待期问题、审核发现。

Input: 你好。
Output: {"facts": []}

Input: 该重疾产品等待期180天，超过《健康保险管理办法》90天上限。
Output: {"facts": ["重疾产品等待期180天", "《健康保险管理办法》规定等待期上限90天"]}

Input: 费率表使用2010年生命表CL1-2010，而非CL1-2023。
Output: {"facts": ["费率表使用过时生命表CL1-2010", "当前应使用CL1-2023"]}

请以 JSON 格式输出。
"""

PROFILE_EXTRACTION_PROMPT = """\
从精算审核对话中提取用户的关注领域和偏好产品类型。
仅提取明确提及的内容，不要推断。

Input:
用户: 这个重疾险的等待期条款合规吗？
助手: 根据《健康保险管理办法》，等待期不得超过90天。
Output: {"focus_areas": ["等待期"], "preference_tags": ["重疾险"]}

Input:
用户: 帮我看看这份意外险的免责条款
助手: 该意外险免责条款第7条将先天性疾病列入免责范围，与《保险法》规定不符。
Output: {"focus_areas": ["免责条款"], "preference_tags": ["意外险"]}

Input:
用户: 你好
助手: 你好，请问有什么可以帮您？
Output: {"focus_areas": [], "preference_tags": []}

请以 JSON 格式输出，仅输出 JSON。
"""
