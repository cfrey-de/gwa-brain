"""GWA Brain — grounded document Q&A with knowledge provenance.

Grounding level: attested ("Stufe 2"), not proven. Every shipped sentence traces to a
named source (document, page, paragraph). There is no compiler oracle here — if a
document is wrong, the fact is wrong. The guarantee is: "the documents say so —
source correctness assumed." See README.md.
"""

__version__ = "0.1.0"
__author__ = "Carsten Frey"
__license__ = "Apache-2.0"
