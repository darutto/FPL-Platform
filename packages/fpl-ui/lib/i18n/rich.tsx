import { Fragment, type ReactNode } from 'react';

/**
 * Fill `{name}` placeholders of an already translated sentence with React nodes, so a name or a
 * figure can be styled inside a sentence whose word order differs between languages.
 * Unknown placeholders stay visible; plain text is passed through untouched.
 */
export function interpolateNodes(text: string, nodes: Record<string, ReactNode>): ReactNode[] {
  return text
    .split(/(\{\w+\})/g)
    .filter((part) => part !== '')
    .map((part, index) => {
      const name = /^\{(\w+)\}$/.exec(part)?.[1];
      return name !== undefined && name in nodes ? <Fragment key={index}>{nodes[name]}</Fragment> : part;
    });
}
