# Data life cycle skills

Skills that let an AI agent do two steps of the research data life cycle in a way a person can
check afterwards: cleaning a dataset and anonymizing it.

A skill is a folder with written instructions (`SKILL.md`) and the scripts those instructions
tell the agent to run. The agent does not write new code for each file. It follows the same
workflow every time, runs the same scripts, never overwrites the raw data and leaves a report of
what it found and what it changed.

These are probes of the CGIAR Digital Transformation Accelerator (Area of Work 3, Technology
Horizons), developed at the International Potato Center (CIP). They are research software, not
finished tools.

## The skills

| Skill | What the agent does with it | Scripts |
| --- | --- | --- |
| [`data_cleaning`](skills/data_cleaning/SKILL.md) | Profiles a table, validates it against rules, applies cleaning actions from a file, validates again and reports. Can look up Crop Ontology and AGROVOC terms to standardize variable and category names. | `profile_dataset.py`, `validate_dataset.py`, `validate_joins.py`, `clean_from_findings.py` |
| [`anonymization`](skills/anonymization/SKILL.md) | Finds columns that may hold personal data, proposes a treatment for each, applies the ones a person confirms and measures the risk that remains (k-anonymity). | `detect_pii.py`, `anonymize_dataset.py`, `check_k_anonymity.py` |

### Data cleaning

Validation uses [Pointblank](https://posit-dev.github.io/pointblank/); cleaning uses pandas.
The rules are conservative on purpose: when the agent is unsure about a value it flags it and
does not change it, and it does not drop rows without saying how many and why.

To standardize terms, the skill points the agent to two open services that speak the Model
Context Protocol (MCP):

- Crop Ontology, 37 crops: `https://CropOntology.fastmcp.app/mcp`
- AGROVOC: `https://agrovoc.fastmcp.app/mcp`

They suggest the standard variable or concept for a name. A person should confirm each mapping.
The source code of both servers is in [`mcp_servers/`](mcp_servers/README.md), with the steps
to run them yourself.

### Anonymization

The scripts run on the researcher's computer and report column names, counts and rates only.
Cell values never reach the language model, so the agent plans the anonymization without
seeing the personal data. The skill reports the k-anonymity reached and on which columns. It
never states that a dataset is anonymous, and a data steward approves the result before the
data is shared.

## Using them

**With an agent.** Copy the folders under `skills/` to wherever your agent loads skills from.
Any agent that reads this layout (a folder with a `SKILL.md` and its scripts) can use them.

**By hand.** The scripts are ordinary command-line programs:

```bash
pip install -r requirements.txt

# Clean: profile, then validate with a key and required columns
python skills/data_cleaning/scripts/profile_dataset.py trial.csv --output validation/profile.json --key plot
python skills/data_cleaning/scripts/validate_dataset.py trial.csv --output validation/checks.json --html validation/checks.html --key plot --not-null genotype

# Anonymize: detect, apply the confirmed actions, measure
python skills/anonymization/scripts/detect_pii.py survey.csv --output anon/detect.json
python skills/anonymization/scripts/anonymize_dataset.py survey.csv --actions actions.json --output anon/survey_v1.csv --report anon/report.json
python skills/anonymization/scripts/check_k_anonymity.py anon/survey_v1.csv --quasi district --quasi sex --quasi age --output anon/risk.json
```

The format of `actions.json` is in the [anonymization skill](skills/anonymization/SKILL.md).

## Tests

```bash
pytest tests
```

The test of the Crop Ontology server is skipped unless its requirements are installed
(`pip install -r mcp_servers/requirements.txt`).

## What has and has not been tested

- The data-cleaning scripts have been run on real, public CIP trial data. How many defects an
  agent repairs with this skill, and how many correct values it alters, has not been measured
  yet; a first measured test with researchers is planned for late November 2026.
- The anonymization skill has been tested on a synthetic survey only. On that survey it flagged
  every direct identifier when column names were informative, and 3 of 7 when they were hidden.
  It has not been used on real survey data, and no data steward has reviewed its output.
- Free-text redaction removes emails, links and long numbers. It does not remove names.

## Credits

Developed by Piero Palacios (CIP), with guidance from Leroy Mwanzia (CIP) and funding from the
CGIAR Digital Transformation Accelerator. Term lookups use [Crop Ontology](https://cropontology.org) and
FAO's [AGROVOC](https://www.fao.org/agrovoc/).

Parts of the code and documentation were written with AI assistance and reviewed by the author.

## License

[Creative Commons Attribution 4.0 International](LICENSE).
