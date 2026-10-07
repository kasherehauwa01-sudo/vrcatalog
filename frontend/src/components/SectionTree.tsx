import { useState } from "react";
import { Box, Checkbox, Collapse, FormControlLabel, IconButton, Stack, TextField, Typography } from "@mui/material";
import { CategoryNode, categoryValue, searchCategoryTree, toggleCategory, toggleSection } from "../categoryTree";

type Props = { tree: CategoryNode[]; categories: string[]; sections: string[];
  onChange: (selection: { category: string[]; section: string[] }) => void };
export function SectionTree({ tree, categories, sections, onChange }: Props) {
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const visible = searchCategoryTree(tree, search);
  return <Box>
    <TextField fullWidth size="small" label="Найти раздел..." value={search} onChange={(e) => setSearch(e.target.value)} sx={{ my: 1 }} />
    <Box sx={{ maxHeight: { xs: "45vh", sm: 400 }, overflowY: "auto", overscrollBehavior: "contain" }}>
      {visible.map((node) => {
        const value = categoryValue(node);
        const original = tree.find((item) => categoryValue(item) === value)!;
        const checked = categories.includes(value);
        const count = original.subcategories.filter((item) => sections.includes(item.name)).length;
        const open = !!search.trim() || (expanded[value] ?? count > 0);
        return <Box key={value}>
          <Stack direction="row" alignItems="center">
            <IconButton aria-label={`${open ? "Свернуть" : "Развернуть"}: ${node.name}`} aria-expanded={open} onClick={() => setExpanded({ ...expanded, [value]: !open })} sx={{ width: 44, height: 44, flexShrink: 0 }}>
              <Box component="span" aria-hidden>{open ? "▾" : "▸"}</Box>
            </IconButton>
            <FormControlLabel sx={{ m: 0, minWidth: 0, overflowWrap: "anywhere" }} control={<Checkbox checked={checked} indeterminate={!checked && count > 0} onChange={() => onChange(toggleCategory(tree, original, categories, sections))} />} label={`${node.name}${count && !checked ? ` · ${count}` : ""}`} />
          </Stack>
          <Collapse in={open} unmountOnExit>
            <Stack sx={{ pl: { xs: 3, sm: 5 } }}>
              {node.subcategories.map((item) => <FormControlLabel key={item.name} sx={{ m: 0, minHeight: 44, overflowWrap: "anywhere" }} control={<Checkbox checked={checked || sections.includes(item.name)} onChange={() => onChange(toggleSection(original, item.name, categories, sections))} />} label={item.name} />)}
            </Stack>
          </Collapse>
        </Box>;
      })}
      {!visible.length && <Typography role="status" sx={{ py: 2 }} color="text.secondary">Ничего не найдено</Typography>}
    </Box>
  </Box>;
}
