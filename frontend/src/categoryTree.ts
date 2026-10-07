export type CategoryNode = {
  id: number | null;
  name: string;
  subcategories: { name: string; product_count: number }[];
};
export const categoryValue = (node: CategoryNode) => node.id === null ? "uncategorized" : String(node.id);
export const normalizeSection = (value: string) => value.trim().replace(/\s+/g, " ").toLocaleLowerCase("ru-RU").replace(/ё/g, "е");
export function searchCategoryTree(tree: CategoryNode[], search: string): CategoryNode[] {
  const term = normalizeSection(search);
  return tree.flatMap((node) => {
    if (!term || normalizeSection(node.name).includes(term)) return [node];
    const subcategories = node.subcategories.filter((item) => normalizeSection(item.name).includes(term));
    return subcategories.length ? [{ ...node, subcategories }] : [];
  });
}
export function toggleCategory(tree: CategoryNode[], node: CategoryNode, categories: string[], sections: string[]) {
  const value = categoryValue(node);
  const children = new Set(node.subcategories.map((item) => item.name));
  return {
    category: categories.includes(value) ? categories.filter((item) => item !== value) : [...categories, value],
    section: sections.filter((item) => !children.has(item)),
  };
}
export function toggleSection(node: CategoryNode, name: string, categories: string[], sections: string[]) {
  const value = categoryValue(node);
  if (categories.includes(value)) {
    // Unchecking one child of a selected category turns it into explicit children.
    return { category: categories.filter((item) => item !== value),
      section: [...new Set([...sections, ...node.subcategories.map((item) => item.name)])].filter((item) => item !== name) };
  }
  return { category: categories, section: sections.includes(name) ? sections.filter((item) => item !== name) : [...sections, name] };
}
