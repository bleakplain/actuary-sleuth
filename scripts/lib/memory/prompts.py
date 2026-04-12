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
根据用户提问和系统回答，提取用户画像信息。仅提取有明确依据的内容，不确定时留空。

Output JSON 格式:
{{"focus_areas": ["关注的保险类型，如重疾险、医疗险"], "preference_tags": ["用户偏好标签，如等待期、免责条款"], "summary": "一句话概括用户当前关注点"}}

用户提问: {question}

系统回答: {answer}

请以 JSON 格式输出。
"""
