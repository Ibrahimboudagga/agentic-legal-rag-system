import textwrap

_SUMMARY_PROMPT = textwrap.dedent("""\
    You are a legal analyst reviewing a contract excerpt.

    Identify the key obligations, rights, and risks for the parties involved.

    Return ONLY a JSON object with exactly these two fields — no markdown, no code block:
    {{
      "summary": "2-3 sentence plain-English summary of what this contract covers and the main obligations of each party",
      "key_risks": "bullet list of the top 3-5 risks, one per line, starting with a dash (e.g. - Risk description)"
    }}

    Contract text:
    {text}
                                  
    # Output:
    
    ```json                              
    """)

_SYNTHESIS_PROMPT = textwrap.dedent("""\
    You are a senior legal analyst preparing a consolidated risk report for a legal team.

    {n} contracts have been individually analyzed. Your task is to:
    - Identify cross-contract patterns and compounding risks
    - Assess the overall risk exposure across the entire batch
    - Recommend specific, actionable steps the legal team should take before signing

    {summaries}

    Return ONLY a JSON object matching this exact schema - no markdown, no code block:
    {{
      "overall_risk_level": "High / Medium / Low - one sentence justifying the rating.",
      "top_cross_contract_risks": "List the top 8 risks that span or compound across contracts. For each risk, name which contracts are affected and explain why it matters.",
      "recommended_actions": "A numbered list of concrete steps the legal team should take."
    }}

    Requirements:
    - top_cross_contract_risks must include at most top 8 risks.
    - recommended_actions must be a numbered list.
    - Do not include any text outside the JSON object.

    Do not include extra keys.

    # Output:
    
    ```json 
    """)

_REVISION_PROMPT = textwrap.dedent("""\
    You are a senior legal analyst. A reviewer has requested changes to the risk report below.

    Rewrite the report in full, incorporating the reviewer's feedback.
    Preserve the same JSON schema as the current report.

    --- CURRENT REPORT ---
    {report}

    --- REVIEWER FEEDBACK ---
    {feedback}

    Return ONLY a JSON object matching this exact schema - no markdown, no code block:
    {{
      "overall_risk_level": "High / Medium / Low - one sentence justifying the rating.",
      "top_cross_contract_risks": "List the top 3 risks that span or compound across contracts. For each risk, name which contracts are affected and explain why it matters.",
      "recommended_actions": "A numbered list of concrete steps the legal team should take."
    }}

    Requirements:
    - top_cross_contract_risks must include exactly 3 risks.
    - recommended_actions must be a numbered list.
    - Apply the reviewer feedback to all relevant fields.
    - Do not include any text outside the JSON object.
    - Do not include extra keys.""")