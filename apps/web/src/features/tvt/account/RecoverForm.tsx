"use client";
import { AccountFlowForm, type AccountFlowFormProps } from "./AccountFlowForm";
export function RecoverForm(props: AccountFlowFormProps) {
  return <AccountFlowForm {...props} purpose="recover" />;
}
