import { useEffect, useMemo, useState } from "react";
import { Box, Checkbox, FormControlLabel, IconButton, Stack, TextField, Typography } from "@mui/material";
import { api } from "../api/client";

type Folder = { name: string; path: string; children: Map<string, Folder> };

function buildTree(paths: string[]) {
  const roots = new Map<string, Folder>();
  for (const path of paths) {
    let level = roots;
    let prefix = "";
    for (const part of path.split("|")) {
      prefix = prefix ? `${prefix}|${part}` : part;
      let folder = level.get(part);
      if (!folder) {
        folder = { name: part.trim(), path: prefix, children: new Map() };
        level.set(part, folder);
      }
      level = folder.children;
    }
  }
  return roots;
}

function searchTree(folders: Map<string, Folder>, term: string): Map<string, Folder> {
  if (!term) return folders;
  const results = new Map<string, Folder>();
  for (const [part, folder] of folders) {
    if (folder.name.toLocaleLowerCase("ru-RU").includes(term)) {
      results.set(part, folder);
    } else {
      const children = searchTree(folder.children, term);
      if (children.size) results.set(part, { ...folder, children });
    }
  }
  return results;
}

type Props = { selected: string[]; onToggle: (path: string) => void };

export function FolderTree({ selected, onToggle }: Props) {
  const [paths, setPaths] = useState<string[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const tree = useMemo(() => buildTree(paths), [paths]);
  const term = search.trim().toLocaleLowerCase("ru-RU");
  const visible = useMemo(() => searchTree(tree, term), [tree, term]);

  useEffect(() => {
    let cancelled = false;
    api.folders().then((result) => {
      if (cancelled) return;
      setPaths(result);
      setStatus("ready");
    }).catch(() => {
      if (!cancelled) setStatus("error");
    });
    return () => { cancelled = true; };
  }, []);

  const renderFolders = (folders: Map<string, Folder>) => Array.from(folders.values(), (folder) => {
    const open = expanded[folder.path] ?? (Boolean(term) || selected.some((path) => path.startsWith(folder.path + "|")));
    return (
      <Box key={folder.path}>
        <Stack direction="row" alignItems="center">
          {folder.children.size > 0 ? (
            <IconButton
              aria-label={`${open ? "Свернуть" : "Развернуть"}: ${folder.name}`}
              aria-expanded={open}
              onClick={() => setExpanded((current) => ({ ...current, [folder.path]: !open }))}
              sx={{ width: 44, height: 44, flexShrink: 0 }}
            >
              <Box component="span" aria-hidden>{open ? "▾" : "▸"}</Box>
            </IconButton>
          ) : <Box sx={{ width: 44, flexShrink: 0 }} />}
          <FormControlLabel
            sx={{ m: 0, minWidth: 0, overflowWrap: "anywhere" }}
            control={<Checkbox checked={selected.includes(folder.path)} onChange={() => onToggle(folder.path)} />}
            label={folder.name}
          />
        </Stack>
        {open && <Box sx={{ pl: { xs: 2, sm: 4 } }}>{renderFolders(folder.children)}</Box>}
      </Box>
    );
  });

  return (
    <Box>
      <TextField
        fullWidth
        size="small"
        label="Найти папку"
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
          setExpanded({});
        }}
        sx={{ my: 1 }}
      />
      <Box sx={{ maxHeight: { xs: "45vh", sm: 400 }, overflowY: "auto", overscrollBehavior: "contain" }}>
        {renderFolders(visible)}
        {!visible.size && (
          <Typography role="status" sx={{ py: 2 }} color={status === "error" ? "error" : "text.secondary"}>
            {status === "loading" ? "Загрузка папок…" : status === "error" ? "Не удалось загрузить папки" : "Папки не найдены"}
          </Typography>
        )}
      </Box>
    </Box>
  );
}
