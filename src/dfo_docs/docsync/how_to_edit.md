How to edit the DFO docs in Google Docs

Each row of the Pages tab is one page of the DFO docs, and the Doc column links to its Google Doc. You edit the text in the Doc. A script copies your edits into the page's source file on GitHub as a pull request, and a reviewer merges it. Nothing you type in a Doc reaches the website until that pull request is merged.

Claim a page

Put your name in the Owner column and set Status to Editing. Put the name of the person who will check the change in Reviewer. Use Notes for anything the next editor should know. Owner, Reviewer, Status and Notes are yours. The script never writes Notes, and fills in every other column.

Edit the Doc

Open the Doc from the Doc column and edit it as you would any document. Change words, fix sentences, add or remove paragraphs and list items, and correct the text in table cells. A line break you add inside a paragraph starts a new paragraph on the site. You can add an item to a list, start a new list after a paragraph, and add links to a "Next" list. A new item goes after the last paragraph of the item above it, a note in that item included.

Use comments freely. You can also use Suggesting mode, but accept or reject every suggestion before you mark the page Ready for review. The script does not read a Doc that still has open suggestions.

Curly quotes become straight quotes when your edits reach GitHub.

Send it to GitHub

When your edits are done, set Status to Ready for review. That is the only thing that sends a page to GitHub. A page with any other Status is never read, so unfinished edits stay in the Doc.

A maintainer runs the script when pages are ready, so tell them when you set a page to Ready for review. Each run opens a new pull request for each source repository, with a section for each page, and puts the link in the PR column. The script never changes a pull request after it opens it, and reviewers may edit it or add commits on GitHub. A page is in one open pull request at a time. Keep editing the Doc while the pull request is open. Those edits are not in it, and they go in the next one once you set Status to Ready for review again.

If a pull request is closed without merging, or is merged without your page, the page returns to Editing, and the Not applied column says why. Your edits stay in the Doc. A page set to Discard my edits is the exception, and its edits are discarded. To drop one page from a pull request that holds several, ask the reviewer to revert that page's file on the pull request branch before merging.

What each Status means

Not started. The script sets this when a page first appears in the Sheet.

Editing. You set this when you claim a page and while you work on it.

Ready for review. You set this when the edits are finished and should go to GitHub. If the Doc holds nothing new to send, the script sets Merged when the page's pull request has just merged and Editing otherwise, and writes "Nothing to send" in the Not applied column.

PR open. The script sets this once it has opened the pull request for the page. Your edits and the reviewer's comments now live on GitHub.

Merged. The script sets this after the pull request is merged and the change has reached the branch the site is built from. To edit the page again, set Status back to Editing.

Discard my edits. You set this to throw away your edits. The next run replaces the Doc with the page from GitHub, even if the Doc has open comments, and sets Status to Editing. A Doc with open suggestions is not replaced until you accept or reject them. While the page's pull request is open, the discard waits. If that pull request was merged into a branch other than the one the page is read from, the discard goes ahead.

What the bold labels mean

Some lines in the Doc start with a bold label. The label marks a part of the page that the site shows in a special way. Edit the text after the label.

Description. The one-sentence summary of the page that search engines and AI assistants read. Keep it to one line. Keep the label. If you delete the whole line, the script ignores that and the pull request reports it. If you remove or change only the label, the script refuses the edit. A line you type above the Description is page text, and the Description stays where it is.

Note, Tip and Warning. A highlighted box on the site. The box holds everything that follows in the same indented block. Edit the text after the label. If you change Note to Tip or Warning, or delete the label, the script ignores the change and the pull request reports it, and the next refresh from GitHub puts the box back. If you remove the label's bold, or delete the label and also change the text, the script refuses the edit. To change the kind of box, ask the reviewer to change it in GitHub.

Author note. A comment for other authors. It stays off the site. Edit the text. Delete all the text after the label, or the whole paragraph, to remove the note. If you change, add or delete a note and also change the page text next to it, with no unchanged paragraph between them, the script applies both and the pull request flags the note once, so the reviewer can check that no text moved between them. It does the same for the Description.

If you remove or change the label, the note becomes a normal paragraph and appears on the site. The pull request flags it so the reviewer can check it belongs there. If you type "Author note:" in bold at the start of a normal paragraph, that paragraph becomes a note and leaves the site, and the pull request flags that too. A new paragraph that starts with the label is a new note. A list item or a heading cannot become a note. The script reports the attempt and changes nothing. A note inside a list item whose label you remove becomes text in that item, and the pull request flags it.

A label belongs at the start of its own paragraph. If you type a bold label in the middle of a paragraph, the script refuses the edit. If you join a note onto the paragraph before or after it, for example by pressing Backspace at the start of the note, or press Enter in the middle of a note, the script refuses the edit, or applies it when the page then matches the Doc and flags the note in the pull request. A paragraph you start with Enter next to a note is a new paragraph, and that works. If the script cannot tell which list item a paragraph next to a note belongs to, it refuses the edit. The script also refuses to add a note, or label a paragraph as one, inside a plain quote, a block whose lines start with ">". A note cannot hold "-->", so the script does not apply such an edit and reports it. When it refuses an edit, nothing in that part of the page changes. Undo the edit, or ask the reviewer to make the change in GitHub.

Tab. A tab heading in a set of tabs. The text after "Tab:" is the name on the tab. Rename it if you need to, but do not add or delete tab lines. If you delete a tab line, the script ignores the change and the pull request reports it. If you remove or change the "Tab:" label and keep the name, or delete a tab line and change the text next to it, the script refuses the edit.

What does not come back from GitHub

The script splices your edits into the source file word by word, so text you did not touch keeps its exact form. If you and someone on GitHub changed different words of one paragraph, both changes stay.

The page layout and the code are kept in the source file. Code blocks, the shape of tables, the tab structure, and everything else that is not text come from GitHub each time the Doc is refreshed.

If you edit a code block or change its language, add or remove a table row or column, add a code block, or delete a Tab line, the script ignores that change and lists it in the pull request as not applied. If you add or remove a bullet or number in front of a paragraph, it applies the text and lists the marker change. When no pull request is opened for the page, the reasons appear in the "Not applied" column instead, the page returns to Editing, and the next run replaces the Doc with the version from GitHub. Check the "Not applied" column after you mark a page ready, and ask the page's reviewer to make any change that was not applied in GitHub.

An edit the script refuses is different. The script refuses the edits described under "What the bold labels mean". If other edits on the page go to a pull request, the pull request quotes your text of the refused part. When that pull request is merged, the Doc is refreshed from GitHub and the refused text leaves it, so ask the reviewer to apply the quoted text or make the edit again in the Doc. If nothing on the page goes to a pull request, the page returns to Editing, your text stays in the Doc, and the run does not replace the Doc. The "Not applied" column gives the reason and quotes your text. A quote too long for the cell is cut. The cut quote ends with a line saying so, and the full text is in the Doc. Undo or change the edit and set Status to Ready for review again, or set Status to Discard my edits to replace the Doc with the page from GitHub.

If you edit a heading, the change goes through, and the pull request notes that links to the old heading may break. Keep headings as they are unless the wording is wrong.

When the Doc is refreshed from GitHub

When a page changes on GitHub, including when your pull request is merged, the script replaces the Doc with the new version. It does this only when the Doc holds no edits that have not reached GitHub, no open comments, and no open suggestions. Replacing a Doc detaches its comments and discards its suggestions.

So resolve every comment and suggestion before a refresh can happen. A Doc with open comments or suggestions keeps its old text until you resolve them. If you have edits that have not reached GitHub, set Status to Ready for review so that they reach GitHub first, or set Discard my edits to drop them.

If someone moves a Doc to the trash or deletes it, the next run creates a new Doc for the page from GitHub and puts its link in the Doc column. A page with an open pull request keeps waiting until the pull request is settled.
