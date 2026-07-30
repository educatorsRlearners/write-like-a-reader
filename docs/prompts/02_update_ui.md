You are a senior UI/UX engineer who has been talking with the company's learning engineer. 

You look at `highlight.py` and realise it missed the point: we don't want to lump all detail questions together or call them "mixed" if they have more than one. 

What we want to do is this: list the exact question(s) raised by each sentence if they are not answered in the proceeding sentence. 

For example, take the first sentence from the following: 

    Social media has changed the way people communicate. Many students use it every day. Some teachers think it is a distraction. The school board is considering a new policy. This would help students focus better because they won't be nearly as distracted by the siren's call that is social media. 

The follow-up questions would be: 
- How do you know? 
- Who says that? 
- When did social media change the way people communicate? 
- How did it change the way people communicate? For better or worse? 

Given that none of those questions were answered in the proceeding sentence, we'd want to ask the writer all of them. 

As such, we want to update `highlight.py` so you can see every question under the sentence like this: 

    Social media has changed the way people communicate. 
        - How do you know? 
        - Who says that? 
        - When did social media change the way people communicate? 
        - How did it change the way people communicate? For better or worse? 

Write a plan explaining how you will update the UI/UX and check your work by asking a senior software engineer to check your work. 