# Example: a vegetarian mealplan vault

The same pattern applied to something non-technical, to show the
range.

---

## The premise

You want to eat better: more vegetarian, enough protein, time-aware
(weeknights are fast, weekends are slow). You've been collecting
recipes and articles for months but they're scattered.

```bash
./init-vault.sh ~/kitchen/mealplan
```

---

## Week 1

You add 10 URLs to `inbox.md`: bon appétit recipes, NYT cooking,
some nutrition articles, a protein-guide from a dietitian's blog.

*"Process and ingest."*

Agent creates:

```
wiki/sources/
  nyt-lentil-soup.md
  bonappetit-tofu-stirfry.md
  examine-protein-requirements.md
  ...
wiki/pages/
  vegetarian-protein.md
  weeknight-cooking.md
  batch-cooking.md
  tofu.md
  tempeh.md
  lentils.md
```

Each source has summary + ingredients + time. Each page cross-links.

---

## Week 2: the view that changes everything

You keep wondering "which protein source actually makes sense for
weeknights?". Too many sources to hold in head.

*"Compare tofu, tempeh, and seitan."* → `/view comparison tofu-tempeh-seitan`

Agent writes `wiki/views/comparison-tofu-tempeh-seitan.md`:

| Dimension | Tofu | Tempeh | Seitan |
|---|---|---|---|
| Protein per 100g | 8g | 19g | 25g |
| Prep time | 10-20 min | 15-25 min | 5-15 min |
| Versatility | High | Medium | Medium |
| Weeknight-friendly | Yes | Yes | Yes |
| Pitfalls | Watery if not pressed | Bitter if not steamed | Gluten |

`shareable: false` — this evolves as you try new preparations.

Now when you ask *"what should I cook tonight?"*, the agent reads
this view and knows your comparative take.

---

## Week 4: reflection

`/reflect`. Agent writes `compass.md`:

> **Where my thinking is going**
>
> You've spent two weeks on weeknight protein options. Hot pages are
> [[wiki/pages/tofu]] (11 hits) and [[wiki/pages/weeknight-cooking]]
> (9 hits). Focus seems to be on 20-minute meals that still feel like
> dinner, not assembly.
>
> **What I'm not looking at**
>
> - [[wiki/pages/batch-cooking]] has strong incoming links but you
>   haven't touched it. Might be the lever for weeknight speed — you
>   prep on Sunday, assemble on Wednesday.
> - No sources on lentils or beans yet, even though they're the
>   cheapest high-protein options.
> - Your comparison view [[wiki/views/comparison-tofu-tempeh-seitan]]
>   never mentions cooking method, only raw properties. Worth adding.
>
> **A question worth sitting with**
>
> You've built a comparison and read fifteen recipes. Have you
> actually changed how you cook on Tuesday night?

The question lands. You realize you've been *reading* about weeknight
cooking without *doing* it. The next week you cook three tofu dishes
from the vault.

---

## Month 3: a shareable artifact

Your parents worry you don't eat enough protein. Family dinner is
coming up.

*"Make a one-page handout on vegetarian protein for my parents, who
don't trust non-meat sources."* → `/view report vegetarian-protein`

Agent asks `shareable`: yes, for your parents. Proposes an outline
(friendly tone, not clinical), writes
`wiki/views/2026-06-20-vegetarian-protein-handout-for-parents.md`
with `shareable: true`.

You print it, give it to them at dinner. Conversation goes better
than last time.

Three months later they ask again. You make a new handout dated
`2026-09-30`, with updated recipes you've tried. The old one stays
as-is, a record of what you told them in June.

---

## What this pattern gives you

The vault isn't primarily "a recipe storage". Recipe storage exists
everywhere. What makes it different:

- **Pages capture understanding**, not just recipes. Your page on
  tofu isn't a recipe — it's what you've learned about tofu over
  months.
- **Views compress decisions**. The comparison isn't a spreadsheet,
  it's your accumulated judgment about which protein works when.
- **`/reflect` catches drift**. Reading without doing is invisible
  unless something points at it.
- **Artifacts for actual people**. The handout isn't for you, it's
  for them. Having a file that knows its audience is freeing.

The pattern works for any domain you want to think with over time:
health, investing, language learning, parenting, a hobby. The agent
doesn't care what the content is about.
