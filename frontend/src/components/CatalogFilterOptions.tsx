import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Button, LinearProgress, Stack, Typography } from "@mui/material";
import { api } from "../api/client";
import type { CategoryNode } from "../categoryTree";

type Options = { values: Record<string, string[]>; tree: CategoryNode[] };

type Props = {
  filterKey: string;
  scope?: string;
  onSectionTree?: (tree: CategoryNode[]) => void;
  children: (options: Options) => ReactNode;
};

export function CatalogFilterOptions({ filterKey, scope, onSectionTree, children }: Props) {
  const [result, setResult] = useState<{ status: "loading" | "error" } | { status: "ready"; options: Options }>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams(scope);
    params.set("filterKey", filterKey);
    const load = filterKey === "section"
      ? api.categoryTree().then((tree) => ({ tree, values: {} }))
      : api.filters(params).then((values) => ({ values, tree: [] }));
    load.then((options) => {
      if (cancelled) return;
      if (filterKey === "section") onSectionTree?.(options.tree);
      setResult({ status: "ready", options });
    }).catch(() => {
      if (!cancelled) setResult({ status: "error" });
    });
    return () => { cancelled = true; };
  }, [attempt, filterKey, onSectionTree, scope]);

  if (result.status === "ready") return children(result.options);
  if (result.status === "error") return (
    <Stack direction="row" alignItems="center" gap={1} sx={{ py: 1 }}>
      <Typography role="alert" variant="body2">Не удалось загрузить значения</Typography>
      <Button size="small" onClick={() => {
        setResult({ status: "loading" });
        setAttempt((value) => value + 1);
      }}>Повторить</Button>
    </Stack>
  );
  return (
    <Stack spacing={0.5} sx={{ py: 1 }} role="status">
      <Typography variant="body2" color="text.secondary">Загружаем значения…</Typography>
      <LinearProgress aria-label="Загрузка значений фильтра" />
    </Stack>
  );
}
