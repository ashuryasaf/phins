page 50109 "PHINS User Account Card"
{
    PageType = Card;
    ApplicationArea = All;
    SourceTable = "PHINS User Account";
    Caption = 'PHINS User Account';

    layout
    {
        area(content)
        {
            group(General)
            {
                field("User ID"; "User ID") { }
                field(Username; Username) { }
                field("Full Name"; "Full Name") { }
                field(Email; Email) { }
                field(Role; Role) { }
                field(Active; Active) { }
            }
        }
    }

    actions
    {
        area(processing)
        {
            action(CreatePasswordHash)
            {
                Caption = 'Set Password (hash)';
                Image = Key;
                RunObject = Codeunit "PHINS User Management";
            }
        }
    }
}
