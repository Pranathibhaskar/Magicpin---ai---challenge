# Magicpin Vera — AI Merchant Assistant

An AI merchant-assistant bot built for the Magicpin AI Challenge.

## Approach

The bot uses a **deterministic, context-aware decision layer** to decide when a merchant should be contacted and what the message should focus on.

The composer receives:

- `CategoryContext`
- `MerchantContext`
- `TriggerContext`
- `CustomerContext` when available

It identifies the strongest actionable signal in the current context and routes it to a trigger-specific messaging strategy. The resulting message follows:

**merchant signal → business implication → concrete next step**

The implementation includes dedicated handling for situations such as:

- Performance spikes and dips
- Renewal reminders
- Campaign and planning intent
- Supply alerts
- Regulation changes
- Customer win-back opportunities
- Review themes
- Seasonal demand changes
- Competitor activity
- Dormant merchants
- Offer and campaign opportunities

A context-grounded fallback is used when a trigger does not have a dedicated strategy.

## Why a deterministic approach?

The challenge rewards **decision quality, specificity, category fit, merchant fit, and engagement**, while also requiring that the assistant avoid hallucinating business facts.

A deterministic approach was chosen because it provides:

- **Grounding:** messages use information present in the supplied context.
- **Predictability:** important business situations have explicit decision logic.
- **Low latency:** there is no external model dependency at runtime.
- **Control:** trigger-specific strategies can prioritize the most relevant signal.
- **Safety:** the system does not need to invent missing merchant information.

The tradeoff is reduced flexibility compared with a general-purpose LLM when encountering completely novel situations. The context-grounded fallback provides coverage for such cases.

## Message Design

The bot aims to make each outbound message:

- Specific to the merchant and current trigger
- Concise and easy to scan
- Grounded in supplied facts
- Focused on one primary business opportunity
- Structured around a single clear CTA
- Free from unsupported claims and unnecessary repetition

The system deliberately avoids turning every available context field into a message. Instead, it tries to select the **one signal most relevant to the merchant's next action**.

## Context and Decision Flow

```text
Category / Merchant / Customer / Trigger Context
                       |
                       v
                 Context Store
                       |
                       v
                Trigger Selection
                       |
                       v
             Priority + Suppression
                       |
                       v
            Trigger-specific Composer
                       |
                       v
            Message + Single CTA
                       |
                       v
                 Merchant Reply
                       |
                       v
                 Reply Handling