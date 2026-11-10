import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: ["dist/**", "node_modules/**", "out/**", "coverage/**"],
  },
  ...tseslint.configs.recommended,
);
