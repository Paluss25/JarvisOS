# JarvisOS Dashboard Design System

## Color

- Background: `#090b10`
- Surface: `#11141b`
- Surface raised: `#171b24`
- Border: `#2a303d`
- Text primary: `#f3f6fb`
- Text secondary: `#9aa4b2`
- Healthy: `#2bd576`
- Warning: `#f5b841`
- Incident: `#ff5c5c`
- Trace: `#4da3ff`
- AI/model: `#a78bfa`
- Network/A2A: `#22d3ee`

## Typography

Use the existing system font stack. Do not scale font size with viewport width.
Dashboard headings are compact. Reserve large type for page titles only.

## Spacing

Use 4px increments. Dense operator views prefer 8px and 12px spacing.

## Layout

Use a fixed sidebar, top command row, main content area, and optional right context drawer.
Do not place UI cards inside other cards.

## Components

Core components: status pills, metric cards, data tables, trace tree, timeline,
action drawer, cockpit panel, decision ledger.

## Motion

Use minimal motion: row highlight, drawer slide, live-update pulse. Avoid decorative animation.

## Voice

Labels are terse and operational: "Running", "Blocked", "Retrying", "Needs review".

## Brand

JarvisOS is an agent operations system. It should feel precise, controlled, and technical.

## Anti-patterns

- No marketing hero.
- No gradient blob backgrounds.
- No card-inside-card.
- No oversized decorative charts.
- No hidden critical status behind hover-only UI.
