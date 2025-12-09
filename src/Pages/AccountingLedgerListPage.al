page 50111 "PHINS Accounting Ledger List"
{
    PageType = List;
    ApplicationArea = All;
    SourceTable = "PHINS Accounting Ledger";
    Caption = 'Accounting Ledger';

    layout
    {
        area(content)
        {
            repeater(Group)
            {
                field("Entry No."; "Entry No.") { }
                field("Allocation ID"; "Allocation ID") { }
                field("Policy ID"; "Policy ID") { }
                field("Account Type"; "Account Type") { }
                field(Debit; Debit) { }
                field(Credit; Credit) { }
                field(Balance; Balance) { }
                field(Posted; Posted) { }
                field("Posted By"; "Posted By") { }
            }
        }
    }

    actions
    {
        area(processing)
        {
            action(ExportCSV)
            {
                Caption = 'Export to CSV';
                Image = Export;
                // Add export logic in future
            }
        }
    }
}
