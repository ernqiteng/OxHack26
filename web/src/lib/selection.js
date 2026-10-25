"use client";

import { createContext, useContext, useState } from "react";

// The one piece of shared state: which decision the user clicked on the map (ICHack26 kept this in Redux).
const SelectionContext = createContext(null);

export function SelectionProvider({ children }) {
  const [selected, setSelected] = useState(null);
  return <SelectionContext.Provider value={{ selected, setSelected }}>{children}</SelectionContext.Provider>;
}

export function useSelection() {
  return useContext(SelectionContext);
}
